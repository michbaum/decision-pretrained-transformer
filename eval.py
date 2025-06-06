import argparse
import os
import pickle

import matplotlib.pyplot as plt
import torch
from IPython import embed

import common_args
from evals import eval_bandit, eval_linear_bandit, eval_darkroom
from net import Transformer, ImageTransformer
from utils import (
    build_bandit_data_filename,
    build_bandit_model_filename,
    build_linear_bandit_data_filename,
    build_linear_bandit_model_filename,
    build_darkroom_data_filename,
    build_darkroom_model_filename,
    build_miniworld_data_filename,
    build_miniworld_model_filename,
)
import numpy as np
import scipy
import time

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    common_args.add_dataset_args(parser)
    common_args.add_model_args(parser)
    common_args.add_eval_args(parser)
    parser.add_argument('--seed', type=int, default=0)

    args = vars(parser.parse_args())
    print("Args: ", args)

    n_envs = args['envs']
    n_hists = args['hists']
    n_samples = args['samples']
    H = args['H']  # Context size
    dim = args['dim']
    state_dim = dim
    action_dim = dim
    n_embd = args['embd']
    n_head = args['head']
    n_layer = args['layer']
    lr = args['lr']
    epoch = args['epoch']
    shuffle = args['shuffle']
    dropout = args['dropout']
    var = args['var']
    cov = args['cov']
    test_cov = args['test_cov']
    envname = args['env']
    horizon = args['hor']  # Horizon used in the MDPs
    n_eval = args['n_eval']
    seed = args['seed']
    lin_d = args['lin_d']
    
    tmp_seed = seed
    if seed == -1:
        tmp_seed = 0

    torch.manual_seed(tmp_seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(tmp_seed)
    np.random.seed(tmp_seed)

    if test_cov < 0:
        test_cov = cov
    if horizon < 0:
        horizon = H[0]

    # (michbaum) Build a model config per model context size in H
    model_configs = []
    filenames = []
    for h in H:
        model_config = {
            'shuffle': shuffle,
            'lr': lr,
            'dropout': dropout,
            'n_embd': n_embd,
            'n_layer': n_layer,
            'n_head': n_head,
            'n_envs': n_envs,
            'n_hists': n_hists,
            'n_samples': n_samples,
            # 'horizon': horizon,
            'horizon': h,
            'dim': dim,
            'seed': seed,
        }
        model_configs.append(model_config)

    if envname == 'bandit':
        state_dim = 1
        
        for mc in model_configs:
            mc.update({'var': var, 'cov': cov})
            # (michbaum) Build a filename per model config
            filename = build_bandit_model_filename(envname, mc)
            filenames.append(filename)
        bandit_type = 'uniform'
    elif envname == 'bandit_bernoulli':
        # NOTE: (michbaum) Broken now, would need changes
        state_dim = 1

        model_config.update({'var': var, 'cov': cov})
        filename = build_bandit_model_filename(envname, model_config)
        bandit_type = 'bernoulli'
    elif envname == 'linear_bandit':
        state_dim = 1

        for mc in model_configs:
            mc.update({'lin_d': lin_d, 'var': var, 'cov': cov})
            filename = build_linear_bandit_model_filename(envname, mc)
            filenames.append(filename)
    elif envname.startswith('darkroom'):
        state_dim = 2
        action_dim = 5
        for mc in model_configs:
            filename = build_darkroom_model_filename(envname, mc)
            filenames.append(filename)
    elif envname == 'miniworld':
        # NOTE: (michbaum) Broken now, would need changes
        state_dim = 2
        action_dim = 4

        filename = build_miniworld_model_filename(envname, model_config)
    else:
        raise NotImplementedError

    models = []
    configs = []
    for h in H:
        config = {
            'horizon': h,
            'state_dim': state_dim,
            'action_dim': action_dim,
            'n_layer': n_layer,
            'n_embd': n_embd,
            'n_head': n_head,
            'dropout': dropout,
            'test': True,
        }
        configs.append(config)

    # Load network from saved file.
    # By default, load the final file, otherwise load specified epoch.
    if envname == 'miniworld':
        # NOTE: (michbaum) Broken now, would need changes
        config.update({'image_size': 25})
        model = ImageTransformer(config).to(device)
    else:
        for config in configs:
            model = Transformer(config).to(device)
            models.append(model)
    
    model_paths = []
    # (michbaum) Build all the model_paths for multiple filenames
    if epoch < 0:
        for tmp_filename in filenames:
            model_path = f'models/{tmp_filename}.pt'
            model_paths.append(model_path)
    else:
        for tmp_filename in filenames:
            model_path = f'models/{tmp_filename}_epoch{epoch}.pt'
            model_paths.append(model_path)

    
    # (michbaum) Load all the models
    for model, model_path in zip(models, model_paths):
        checkpoint = torch.load(model_path)
        model.load_state_dict(checkpoint)
        model.eval()

    # TODO: (michbaum) Need to somehow change filename
    dataset_config = {
        'horizon': horizon,
        'dim': dim,
    }
    ctx_sizes = "_".join([str(h) for h in H])
    if envname in ['bandit', 'bandit_bernoulli']:
        dataset_config.update({'var': var, 'cov': cov, 'type': 'uniform'})
        eval_filepath = build_bandit_data_filename(
            envname, n_eval, dataset_config, mode=2)
        save_filename = f'{filename}_testcov{test_cov}_hor{horizon}_context_sizes_{ctx_sizes}.pkl'
    elif envname in ['linear_bandit']:
        dataset_config.update({'lin_d': lin_d, 'var': var, 'cov': cov})
        eval_filepath = build_linear_bandit_data_filename(
            envname, n_eval, dataset_config, mode=2)
        save_filename = f'{filename}_testcov{test_cov}_hor{horizon}_context_sizes_{ctx_sizes}.pkl'
    elif envname in ['darkroom_heldout', 'darkroom_permuted']:
        dataset_config.update({'rollin_type': 'uniform'})
        eval_filepath = build_darkroom_data_filename(
            envname, n_eval, dataset_config, mode=2)
        save_filename = f'{filename}_hor{horizon}_context_sizes_{ctx_sizes}.pkl'
    elif envname == 'miniworld':
        dataset_config.update({'rollin_type': 'uniform'})        
        eval_filepath = build_miniworld_data_filename(
            envname, 0, n_eval, dataset_config, mode=2)
        save_filename = f'{filename}_hor{horizon}_context_sizes_{ctx_sizes}.pkl'
    else:
        raise ValueError(f'Environment {envname} not supported')

    with open(eval_filepath, 'rb') as f:
        eval_trajs = pickle.load(f)

    n_eval = min(n_eval, len(eval_trajs))

    evals_filename = f"evals_epoch{epoch}"
    if not os.path.exists(f'figs/{evals_filename}'):
        os.makedirs(f'figs/{evals_filename}', exist_ok=True)
    if not os.path.exists(f'figs/{evals_filename}/bar'):
        os.makedirs(f'figs/{evals_filename}/bar', exist_ok=True)
    if not os.path.exists(f'figs/{evals_filename}/online'):
        os.makedirs(f'figs/{evals_filename}/online', exist_ok=True)
    if not os.path.exists(f'figs/{evals_filename}/graph'):
        os.makedirs(f'figs/{evals_filename}/graph', exist_ok=True)

    # Online and offline evaluation.
    if envname == 'bandit' or envname == 'bandit_bernoulli':
        config = {
            'horizon': horizon,
            'H': H,
            'var': var,
            'n_eval': n_eval,
            'bandit_type': bandit_type,
        }
        eval_bandit.online(eval_trajs, models, **config)
        plt.savefig(f'figs/{evals_filename}/online/{save_filename}.png')
        plt.clf()
        plt.cla()
        plt.close()

        # eval_bandit.offline(eval_trajs, models, **config)
        # plt.savefig(f'figs/{evals_filename}/bar/{save_filename}_bar.png')
        # plt.clf()

        eval_bandit.offline_graph(eval_trajs, models, **config)
        plt.savefig(f'figs/{evals_filename}/graph/{save_filename}_graph.png')
        plt.clf()

    # TODO: (michbaum) Adapt
    elif envname == 'linear_bandit':
        config = {
            'horizon': horizon,
            'var': var,
            'n_eval': n_eval,
        }

        # with open(eval_filepath, 'rb') as f:
        #     eval_trajs = pickle.load(f)

        eval_linear_bandit.online(eval_trajs, models, **config)
        plt.savefig(f'figs/{evals_filename}/online/{save_filename}.png')
        plt.clf()
        plt.cla()
        plt.close()

        eval_linear_bandit.offline(eval_trajs, models, **config)
        plt.savefig(f'figs/{evals_filename}/bar/{save_filename}_bar.png')
        plt.clf()

        eval_linear_bandit.offline_graph(eval_trajs, models, **config)
        plt.savefig(f'figs/{evals_filename}/graph/{save_filename}_graph.png')
        plt.clf()

    elif envname in ['darkroom_heldout', 'darkroom_permuted']:
        config = {
            'Heps': 40,
            'horizon': horizon,
            'H': H,
            'n_eval': min(20, n_eval),
            'dim': dim,
            'permuted': True if envname == 'darkroom_permuted' else False,
        }
        eval_darkroom.online(eval_trajs, models, **config)
        plt.savefig(f'figs/{evals_filename}/online/{save_filename}.png')
        plt.clf()

        # del config['Heps']
        # del config['horizon']
        # config['n_eval'] = n_eval
        # eval_darkroom.offline(eval_trajs, models, **config)
        # plt.savefig(f'figs/{evals_filename}/bar/{save_filename}_bar.png')
        # plt.clf()

    elif envname == 'miniworld':
        # NOTE: (michbaum) Broken now
        from evals import eval_miniworld
        save_video = args['save_video']
        filename_prefix = f'videos/{save_filename}/{evals_filename}/'
        config = {
            'Heps': 40,
            'horizon': horizon,
            'H': H,
            'n_eval': min(20, n_eval),
            'save_video': save_video,
            'filename_template': filename_prefix + '{controller}_env{env_id}_ep{ep}_online.gif',
        }

        if save_video and not os.path.exists(f'videos/{save_filename}/{evals_filename}'):
            os.makedirs(
                f'videos/{save_filename}/{evals_filename}', exist_ok=True)

        eval_miniworld.online(eval_trajs, model, **config)
        plt.savefig(f'figs/{evals_filename}/online/{save_filename}.png')
        plt.clf()

        del config['Heps']
        del config['horizon']
        del config['H']
        config['n_eval'] = n_eval
        config['filename_template'] = filename_prefix + \
            '{controller}_env{env_id}_offline.gif'
        start_time = time.time()
        eval_miniworld.offline(eval_trajs, model, **config)
        print(f'Offline evaluation took {time.time() - start_time} seconds')
        plt.savefig(f'figs/{evals_filename}/bar/{save_filename}_bar.png')
        plt.clf()

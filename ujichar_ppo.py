import os
import torch
import pprint
import argparse
import numpy as np
from torch.utils.tensorboard import SummaryWriter

import gym
import normflow_policy

from tianshou.env import SubprocVectorEnv
from tianshou.policy import PPOPolicy
from tianshou.policy.dist import DiagGaussian
from tianshou.trainer import onpolicy_trainer
from tianshou.data import Collector, ReplayBuffer
from tianshou.utils.net.common import Net
from tianshou.utils.net.continuous import ActorProb, Critic

# from normflow_policy.env.ujichar_handwriting import UJICharHandWritingEnv 

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', type=str, default='UJICharHandwriting-v0')
    parser.add_argument('--seed', type=int, default=1626)
    parser.add_argument('--buffer-size', type=int, default=20000)
    parser.add_argument('--lr', type=float, default=1e-3)
    parser.add_argument('--gamma', type=float, default=1.)
    parser.add_argument('--epoch', type=int, default=200)
    parser.add_argument('--step-per-epoch', type=int, default=100)
    parser.add_argument('--collect-per-step', type=int, default=1)
    parser.add_argument('--repeat-per-collect', type=int, default=2)
    parser.add_argument('--batch-size', type=int, default=128)
    parser.add_argument('--layer-num', type=int, default=1)
    parser.add_argument('--training-num', type=int, default=16)
    parser.add_argument('--test-num', type=int, default=100)
    parser.add_argument('--logdir', type=str, default='log')
    parser.add_argument('--render', type=float, default=0.)
    parser.add_argument(
        '--device', type=str,
        default='cuda' if torch.cuda.is_available() else 'cpu')
    # ppo special
    parser.add_argument('--vf-coef', type=float, default=0.5)
    parser.add_argument('--ent-coef', type=float, default=0.01)
    parser.add_argument('--eps-clip', type=float, default=0.2)
    parser.add_argument('--max-grad-norm', type=float, default=0.5)
    parser.add_argument('--gae-lambda', type=float, default=0.95)
    parser.add_argument('--rew-norm', type=int, default=1)
    parser.add_argument('--dual-clip', type=float, default=None)
    parser.add_argument('--value-clip', type=int, default=1)
    args = parser.parse_known_args()[0]
    return args

def test_ppo(args=get_args()):
    env = gym.make(args.task)
    args.state_shape = env.observation_space.shape
    args.action_shape = env.action_space.shape
    args.max_action = env.action_space.high[0]
    # train_envs = gym.make(args.task)
    train_envs = SubprocVectorEnv([
        lambda: gym.make(args.task)
        for _ in range(args.training_num)])
    # test_envs = gym.make(args.task)
    test_envs = SubprocVectorEnv([
        lambda: gym.make(args.task)
        for _ in range(args.test_num)])
    # seed
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    train_envs.seed(args.seed)
    test_envs.seed(args.seed)
    # model
    net = Net(args.layer_num, args.state_shape, device=args.device)
    actor = ActorProb(
        net, args.action_shape,
        args.max_action, args.device
    ).to(args.device)
    critic = Critic(Net(
        args.layer_num, args.state_shape, device=args.device
    ), device=args.device).to(args.device)
    optim = torch.optim.Adam(list(
        actor.parameters()) + list(critic.parameters()), lr=args.lr)
    dist = DiagGaussian
    policy = PPOPolicy(
        actor, critic, optim, dist, args.gamma,
        max_grad_norm=args.max_grad_norm,
        eps_clip=args.eps_clip,
        vf_coef=args.vf_coef,
        ent_coef=args.ent_coef,
        reward_normalization=args.rew_norm,
        # dual_clip=args.dual_clip,
        # dual clip cause monotonically increasing log_std :)
        value_clip=args.value_clip,
        # action_range=[env.action_space.low[0], env.action_space.high[0]],)
        # if clip the action, ppo would not converge :)
        gae_lambda=args.gae_lambda)
    # collector
    train_collector = Collector(
        policy, train_envs, ReplayBuffer(args.buffer_size),
        preprocess_fn=None)
    test_collector = Collector(policy, test_envs, preprocess_fn=None)
    # log
    log_path = os.path.join(args.logdir, args.task, 'ppo')
    writer = SummaryWriter(log_path)

    def save_fn(policy):
        torch.save(policy.state_dict(), os.path.join(log_path, 'policy.pth'))

    def stop_fn(x):
        # if env.spec.reward_threshold:
        #     return x >= env.spec.reward_threshold
        # else:
        #     return False
        return x >= 200 #handdesigned reward threshold, what is this?

    # trainer
    # def train_preprocess_fn(epoch):
    #     print(list(policy.actor.parameters())) 
    result = onpolicy_trainer(
        policy, train_collector, test_collector, args.epoch,
        args.step_per_epoch, args.collect_per_step, args.repeat_per_collect,
        args.test_num, args.batch_size, stop_fn=stop_fn, save_fn=save_fn,
        writer=writer)
    train_collector.close()
    test_collector.close()
    if __name__ == '__main__':
        pprint.pprint(result)
        # Let's watch its performance!
        env = gym.make(args.task)
        collector = Collector(policy, env, preprocess_fn=None)
        result = collector.collect(n_step=100, render=args.render)
        print('Final reward: {0}, length: {1}'.format(result["rew"], result["len"]))
        collector.close()


if __name__ == '__main__':
    test_ppo()
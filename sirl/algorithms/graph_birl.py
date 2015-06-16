
from __future__ import division
from abc import ABCMeta, abstractmethod

from numpy.random import choice, randint
import numpy as np

from .mdp_solvers import graph_policy_iteration
from ..base import ModelMixin


class RewardLoss(object):
    """docstring for RewardLoss"""
    def __init__(self, arg):
        self.arg = arg


########################################################################
# Reward Priors

class RewardPrior(ModelMixin):
    """ Reward prior interface """
    __meta__ = ABCMeta

    def __init__(self, name):
        self.name = name

    @abstractmethod
    def __call__(self, r):
        raise NotImplementedError('Abstract method')

    @abstractmethod
    def log_p(self, r):
        raise NotImplementedError('Abstract method')


class UniformRewardPrior(RewardPrior):
    """ Uniform/flat prior"""
    def __init__(self, name='uniform'):
        super(UniformRewardPrior, self).__init__(name)

    def __call__(self, r):
        return r

    def log_p(self, r):
        return np.log(r)


class GaussianRewardPrior(RewardPrior):
    """Gaussian reward prior"""
    def __init__(self, name='gaussian', sigma=0.5):
        super(GaussianRewardPrior, self).__init__(name)
        self._sigma = sigma

    def __call__(self, r):
        return np.exp(-np.square(r)/(2.0*self._sigma**2)) /\
            np.sqrt(2.0*np.pi)*self._sigma

    def log_p(self, r):
        # TODO - make analytical
        return np.log(self.__call__(r))


class LaplacianRewardPrior(RewardPrior):
    """Laplacian reward prior"""
    def __init__(self, name='laplace', sigma=0.5):
        super(LaplacianRewardPrior, self).__init__(name)
        self._sigma = sigma

    def __call__(self, r):
        return np.exp(-np.fabs(r)/(2.0*self._sigma)) / (2.0*self._sigma)

    def log_p(self, r):
        # TODO - make analytical
        return np.log(self.__call__(r))


########################################################################
# Algorithms

class GBIRL(ModelMixin):
    """GraphBIRL algorithm

    This is an iterative algorithm that improves the reward based on the
    quality differences between expert trajectories and trajectories
    generated by the test rewards

    """

    __meta__ = ABCMeta

    def __init__(self, demos, mdp, prior, loss, alpha=0.9, max_iter=10):
        self._demos = demos
        self._prior = prior
        self._mdp = mdp
        self._loss = loss
        self._alpha = alpha
        self._max_iter = max_iter

    def solve(self):
        """ Find the true reward function """

        # - initialize
        e_trajs = self._demos
        reward = self._initial_reward()
        pi0 = self._compute_policy(reward=reward)
        g_trajs = self._generate_trajestories(pi0, size=10)

        for iteration in range(self._max_iter):
            # - Compute reward likelihood, find the new reward
            reward = self.find_next_reward(e_trajs, g_trajs)

            # - generate trajectories using current reward and store
            new_policy = self._compute_policy(reward)
            g_trajs = self._generate_trajestories(new_policy)

        return reward

    @abstractmethod
    def find_next_reward(self, e_trajs, g_trajs):
        """ Compute a new reward based on current iteration """
        raise NotImplementedError('Abstract')

    @abstractmethod
    def initialize_reward(self):
        """ Initialize reward function based on sovler """
        raise NotImplementedError('Abstract')

    # -------------------------------------------------------------
    # internals
    # -------------------------------------------------------------

    def _generate_trajestories(self, policy, size=10):
        """ Generate trajectories using a given policy """
        # TODO - remove the need for arguiments as all info is in graph
        self._mdp._find_best_policies()
        return self._mdp._best_trajs

    def _compute_policy(self, reward):
        """ Compute the policy induced by a given reward function """
        # TODO - check that reward is a weight vector
        gea = self._mdp.graph.gea
        sea = self._mdp.graph.sea

        for e in self._mdp.graph.all_edges:
            phi = gea(e[0], e[1], 'phi')
            r = np.dot(phi, reward)
            sea(e[0], e[1], 'reward', r)

        graph_policy_iteration(self._mdp)
        # TODO - remove the need to return pi as its stored in graph
        policy = self._mdp.graph.policy
        return policy

    def compute_expert_trajectory_quality(self, reward, gr):
        """ Compute the Q-function of expert trajectories """
        G = self._mdp.graph

        QEs = []
        for traj in self._demos:
            time = 0
            QE = 0
            for n in traj:
                actions = G.out_edges(n)
                if actions:
                    e = actions[G.gna(n, 'pi')]
                    r = np.dot(reward, G.gea(e[0], [1], 'phi'))
                    QE += (self.mdp.gamma ** time) * r
                    time += G.gea(e[0], [1], 'duration')
                else:
                    QE += (self.mdp.gamma ** time) * gr
            QEs.append(QE)
        return QEs

    def compute_generated_trajectory_quality(self, g_trajs, reward, gr):
        """ Compute the Q-function of generated trajectories """
        G = self._mdp.graph

        QPiv = []
        for g_traj in g_trajs:
            QPis = []
            for traj in g_traj:
                QPi = 0
                time = 0
                for n in traj:
                    actions = G.out_edges(n)
                    if actions:
                        e = actions[G.gna(n, 'pi')]
                        r = np.dot(reward, G.gea(e[0], [1], 'phi'))
                        QPi += (self.mdp.gamma ** time) * r
                        time += G.gea(e[0], [1], 'duration')
                    else:
                        QPi += (self.mdp.gamma ** time) * gr
                QPis.append(QPi)
            QPiv.append(QPis)
        return QPiv


########################################################################

# MCMC proposals

class Proposal(ModelMixin):
    """ Proposal for MCMC sampling """
    def __init__(self, dim):
        self.dim = dim

    @abstractmethod
    def __call__(self, loc):
        raise NotImplementedError('Abstract class')


class PolicyWalkProposal(Proposal):
    """ PolicyWalk MCMC proposal """
    def __init__(self, dim, delta, bounded=True):
        super(PolicyWalkProposal, self).__init__(dim)
        self.delta = delta
        self.bounded = bounded

    def __call__(self, loc):
        new_loc = np.array(loc)
        changed = False
        while not changed:
            d = choice([-self.delta, 0, self.delta])
            i = randint(self.dim)
            if self.bounded:
                if -1 <= new_loc[i]+d <= 1:
                    new_loc[i] += d
                    changed = True
            else:
                new_loc[i] += d
                changed = True
        return new_loc


# PolicyWalk based GraphBIRL


class GBIRLPolicyWalk(GBIRL):
    """GraphBIRL algorithm using PolicyWalk MCMC

    """
    def __init__(self, demos, mdp, prior, loss, step_size=1/5.0,
                 max_iter=10, alpha=0.9, reward_max=1., mcmc_iter=50):
        super(GBIRLPolicyWalk, self).__init__(demos, mdp, prior, loss,
                                              alpha, max_iter)
        self._delta = step_size
        self._rmax = reward_max
        self._mcmc_iter = mcmc_iter

    def find_next_reward(self, e_trajs, g_trajs):
        """ Compute a new reward based on current iteration using PW """
        pass

    def initialize_reward(self):
        """
        Generate initial reward for the algorithm in $R^{|S| / \delta}$
        """
        rdim = self._mdp._reward.dim
        v = np.arange(-self._rmax, self._rmax+self._delta, self._delta)
        reward = np.zeros(rdim)
        for i in range(rdim):
            reward[i] = np.random.choice(v)
        return reward

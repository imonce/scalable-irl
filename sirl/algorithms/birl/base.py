from __future__ import division

import warnings
from abc import ABCMeta, abstractmethod
from copy import deepcopy

import numpy as np
from numpy.random import choice, randint

from ...models.base import ModelMixin
from ...utils.common import Logger
from ..mdp_solvers import graph_policy_iteration


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
        rp = np.ones(r.shape[0])
        dist = rp / np.sum(rp)
        return dist

    def log_p(self, r):
        return np.log(self.__call__(r))


class GaussianRewardPrior(RewardPrior):
    """Gaussian reward prior"""
    def __init__(self, name='gaussian', sigma=0.5):
        super(GaussianRewardPrior, self).__init__(name)
        self._sigma = sigma

    def __call__(self, r):
        rp = np.exp(-np.square(r)/(2.0*self._sigma**2)) /\
            np.sqrt(2.0*np.pi)*self._sigma
        return rp / np.sum(rp)

    def log_p(self, r):
        # TODO - make analytical
        return np.log(self.__call__(r))


class LaplacianRewardPrior(RewardPrior):
    """Laplacian reward prior"""
    def __init__(self, name='laplace', sigma=0.5):
        super(LaplacianRewardPrior, self).__init__(name)
        self._sigma = sigma

    def __call__(self, r):
        rp = np.exp(-np.fabs(r)/(2.0*self._sigma)) / (2.0*self._sigma)
        return rp / np.sum(rp)

    def log_p(self, r):
        # TODO - make analytical
        return np.log(self.__call__(r))


########################################################################
# MCMC proposals

class Proposal(ModelMixin):
    """ Proposal for MCMC sampling """
    __meta__ = ABCMeta

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
        # TODO - allow setting bounds as list of arrays

    def __call__(self, loc):
        new_loc = np.array(loc)
        changed = False
        while not changed:
            d = choice([-self.delta, self.delta])
            i = randint(self.dim)
            if self.bounded:
                if -1 <= new_loc[i]+d <= 1:
                    new_loc[i] += d
                    changed = True
            else:
                new_loc[i] += d
                changed = True
        return new_loc


########################################################################
# BIRL (Bayesian IRL) base interface

class BIRL(ModelMixin, Logger):
    """ Bayesian Inverse Reinforcement Learning

    BIRL algorithm that seeks to find a reward function underlying a set of
    expert demonstrations by computing the posterior of the reward distribution
    :math:`p(r | \Xi)`.

    The algorithms typically summarize the distribution by taking a single
    value such as the mode, or mean.


    Parameters
    ----------
    demos : array-like
        Expert demonstrations as set of M trajectories of state action pairs.
        Trajectories can be of different lengths.
    rep : A representation object
        The underlying representation of the MDP for the task, can be a
        :class:`ControllerGraph`, or any derivative of the representation
        interface :class:`MDPRepresentation`
    prior : :class:``RewardPrior`` or derivative object
        Reward prior callable object
    loss : A callable object, derivative of :class:`RewardLoss`
        Reward loss callable, for evaluating progress in reward search
    beta : float, optional (default=0.9)
        Expert optimality parameter for the reward likelihood term in the
        product of exponential distributions


    Attributes
    ----------
    _demos : array-like
        Expert demonstrations as set of M trajectories of state action pairs.
        Trajectories can be of different lengths.
    _rep : A representation object
        The underlying representation of the MDP for the task, can be a
        :class:`ControllerGraph`, or any derivative of the representation
        interface :class:`MDPRepresentation`
    _prior : :class:``RewardPrior`` or derivative object
        Reward prior callable object
    _loss : A callable object, derivative of :class:`RewardLoss`
        Reward loss callable, for evaluating progress in reward search
    _beta : float, optional (default=0.9)
        Expert optimality parameter for the reward likelihood term in the
        product of exponential distributions

    """
    __meta__ = ABCMeta

    def __init__(self, demos, rep, prior, loss, beta=0.7):
        self._demos = demos
        self._prior = prior
        self._rep = rep
        self._loss = loss

        assert 0.0 < beta <= 1.0, '*beta* must be in (0, 1]'
        self._beta = beta

    @abstractmethod
    def solve(self):
        """ Find the true reward function """
        raise NotImplementedError('Abstract')

    @abstractmethod
    def initialize_reward(self):
        """ Initialize reward function based on sovler """
        raise NotImplementedError('Abstract')


########################################################################
# Generative type Iterative BIRL Algorithm

class GeneratingTrajectoryBIRL(BIRL):
    """ Generating Trajectory based BIRL (GTBIRL)

    Bayesian Inverse Reinforcement Learning on Adaptive State Graph by
    generation of new trajectories and comparing Q values

    This is an iterative algorithm that improves the reward based on the
    quality differences between expert trajectories and trajectories
    generated by the test rewards

    """

    __meta__ = ABCMeta

    def __init__(self, demos, rep, prior, loss, beta=0.7, max_iter=10):
        super(GeneratingTrajectoryBIRL, self).__init__(demos, rep, prior,
                                                       loss, beta)
        max_iter = int(max_iter)
        assert 0 < max_iter, '*max_iter* must be > 0'
        if max_iter > 1000:
            warnings.warn('*max_iter* set to high value: {}'.format(max_iter))
        self._max_iter = max_iter

    def solve(self):
        """ Find the true reward function

        Iteratively find the reward by generating trajectories using new
        approximations and comparing the quality with the expert demos

        """
        reward = self.initialize_reward()
        # self._compute_policy(reward=reward)
        # init_g_trajs = self._rep.find_best_policies()

        g_trajs = [deepcopy(self._demos)]

        for iteration in range(self._max_iter):
            # - Compute reward likelihood, find the new reward
            reward = self.find_next_reward(g_trajs)

            # - generate trajectories using current reward and store
            self._compute_policy(reward)
            trajs = self._rep.find_best_policies()
            g_trajs.append(trajs)

            # g_trajs = [trajs]

            self.info('Iteration: {}'.format(iteration))

        return reward

    @abstractmethod
    def find_next_reward(self, g_trajs):
        """ Compute a new reward based on current iteration """
        raise NotImplementedError('Abstract')

    @abstractmethod
    def initialize_reward(self):
        """ Initialize reward function based on sovler """
        raise NotImplementedError('Abstract')

    # -------------------------------------------------------------
    # internals
    # -------------------------------------------------------------

    def _compute_policy(self, reward):
        """ Compute the policy induced by a given reward function """
        self._rep = self._rep.update_rewards(reward)
        graph_policy_iteration(self._rep.graph,
                               self._rep.mdp.gamma)

    def _expert_trajectory_quality(self, reward):
        """ Compute the Q-function of expert trajectories """
        G = self._rep.graph
        gr = 100  # TODO - make configurable
        gamma = self._rep.mdp.gamma

        QEs = []
        for traj in self._demos:
            time = 0
            QE = 0
            for n in traj:
                actions = G.out_edges(n)
                if actions:
                    e = actions[G.gna(n, 'pi')]
                    r = np.dot(reward, G.gea(e[0], e[1], 'phi'))
                    QE += (gamma ** time) * r
                    time += G.gea(e[0], e[1], 'duration')
                else:
                    QE += (gamma ** time) * gr
            QEs.append(QE)
        return QEs

    def _generated_trajectory_quality(self, reward, g_trajs):
        """ Compute the Q-function of generated trajectories """
        G = self._rep.graph
        gr = 100
        gamma = self._rep.mdp.gamma

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
                        r = np.dot(reward, G.gea(e[0], e[1], 'phi'))
                        QPi += (gamma ** time) * r
                        time += G.gea(e[0], e[1], 'duration')
                    else:
                        QPi += (gamma ** time) * gr
                QPis.append(QPi)
            QPiv.append(QPis)
        return QPiv

from __future__ import division

import warnings
import pickle

import networkx as nx

from numpy import asarray, sqrt


class StateGraph(object):
    """ State Graph

    The state graph encapsulates a flexible representation for an MDP which
    affords use of task specific constraints as well as temporally extended
    actions (in the sense of hierarchical reinforcement learning, options)

    """

    _node_attrs = ('data', 'cost', 'priority', 'Q', 'V', 'pi', 'type')
    _edge_attrs = ('source', 'target', 'duration', 'reward', 'phi', 'traj')

    def __init__(self, state_dim=4):
        self._graph = nx.DiGraph()

        assert state_dim > 0, 'State dimension must be greater than 0'
        self._state_dim = state_dim

    def clear(self):
        self.G.clear()

    def add_node(self, nid, data, cost, priority, Q, V, pi, ntype):
        """
        Add a new node to the graph
        """
        data = asarray(data)
        assert len(data) == self._state_dim,\
            'Expecting a {}-dim state vector for node'.format(self._state_dim)

        if nid not in self.G:
            self.G.add_node(nid, data=data, cost=cost, priority=priority,
                            Q=Q, V=V, pi=pi, type=ntype)
        else:
            warnings.warn('Node already exits in the graph, not added')

    def add_edge(self, source, target, duration, reward, phi, traj):
        """
        Add a new edge into the graph
        """
        assert duration >= 0.0, 'Duration must be positive'
        phi = asarray(phi)
        traj = asarray(traj)
        assert traj.ndim == 2, 'Expecting a 2-dim dim trajectory'

        if source == target:
            warnings.warn('source: {} and target: {} nodes are the same'.
                          format(source, target))

        elif not self.G.has_edge(source, target):
            self.G.add_edge(source, target, duration=duration,
                            reward=reward, phi=phi, traj=traj)
        else:
            warnings.warn('Edge ({}--{}) already exists in the graph'
                          .format(source, target))

    def remove_edge(self, source, target):
        """ Remove an edge from the graph """
        if source == target:
            warnings.warn('source: {} and target: {} nodes are the same'.
                          format(source, target))

        self.G.remove_edge(source, target)

    def remove_node(self, node):
        """ Remove a node from the graph """
        self.G.remove_node(node)

    def edge_exists(self, source, target):
        """ Check if an edge already exists in the graph """
        return self.G.has_edge(source, target)

    def gna(self, node_id, attribute):
        """
        Get a single attribute of a single node
        Parameters
        ------------
        node_id : int
        attribute : string
        """
        self._check_node_attributes(node_id, attribute)
        return self.G.node[node_id][attribute]

    def sna(self, node_id, attribute, value):
        """
        Set a single attribute of a node
        Parameters
        ------------
        node_id : int
        attribute : string
        value : any
        """
        self._check_node_attributes(node_id, attribute)
        self.G.node[node_id][attribute] = value

    def gea(self, source, target, attribute):
        """
        Get a single attribute of a single edge
        """
        self._check_edge_attributes(source, target, attribute)
        return self.G.edge[source][target][attribute]

    def sea(self, source, target, attribute, value):
        """
        Set a single attribute of a edge between source and target
        """
        self._check_edge_attributes(source, target, attribute)
        self.G.edge[source][target][attribute] = value

    def find_neighbors_from_pose(self, loc, distance):
        """ Find node neighbors within distance range
        Note
        -----
        Includes self in the result
        """
        neighbors = filter(lambda n: eud(self.gna(n, 'data'), loc) <= distance,
                           self.G.nodes())
        return list(neighbors)

    def find_neighbors_range(self, nid, distance):
        """ Find node neighbors within distance range
        Note
        -----
        Includes self in the result
        """
        cn = self.gna(nid, 'data')
        serch_set = set(self.G.nodes()) - {nid}
        neighbors = filter(lambda n: eud(self.gna(n, 'data'), cn) <= distance,
                           serch_set)
        return list(neighbors)

    def find_neighbors_k(self, nid, k):
        """ Find k nearest neighbors based on Euclidean distance """
        serch_set = set(self.G.nodes()) - {nid}
        cn = self.gna(nid, 'data')
        distances = {n: eud(self.gna(n, 'data'), cn) for n in serch_set}
        sorted_neighbors = sorted(distances.items(), key=lambda x: x[1])
        k_neighbors = sorted_neighbors[:k]
        return list(n[0] for n in k_neighbors)

    def neighbors(self, nid):
        """ Get the connected node neighbors """
        return self.G.neighbors(nid)

    def edges(self, nid):
        """ Return the edges of a node """
        return self.G.edges(nid)

    def out_edges(self, nid):
        """ Return the outgoing edges of a node """
        return self.G.out_edges(nid)

    def filter_nodes_by_type(self, ntype):
        """ Filter nodes by node type """
        sns = filter(lambda n: self.gna(n, 'type') == ntype, self.nodes)
        return list(sns)

    def search_path(self, source, target):
        """ Search for a path from ``source`` to ``target`` using A*"""
        def metric(a, b):
            if self.edge_exists(source, target):
                return -1*self.gea(source, target, 'reward')
            return 1000
        path = nx.astar_path(self.G, source, target, heuristic=metric)
        return path

    def get_signal(self, name):
        """ Retrieve a graph signal from the nodes

        The signals correspond to the node attributes in the graph. For Q
        values, the signal is a list of lists, each of varying lengths since
        the number of edges vary per node.

        Parameters
        -----------
        name : str
            Name of signal to retrieve

        Returns
        -------
        signal : array-like
            1D array for Cost, V, and policy; and a list of lists for Q

        """
        assert name in ('cost', 'policy', 'priority', 'V', 'Q')
        return [self.gna(n, name) for n in self.nodes]

    def save_graph(self, filename):
        """ Save the graph to file """
        with open(filename, 'wb') as f:
            pickle.dump(self._graph, f)

    def load_graph(self, filename):
        """ Load a graph from file """
        with open(filename, 'rb') as f:
            self._graph = pickle.load(f)

    def plot_graph(self, ax=None, path=[]):
        """
        Save the graph to file
        """
        ncolors = {'simple': 'orange', 'path': 'r', 'start': 'b', 'goal': 'g'}
        ecolors = {'simple': 'k', 'path': 'r', 'start': 'b', 'goal': 'g'}

        nodes = self.G.nodes(data=True)
        node_list = list()
        node_color_array = list()
        for n in nodes:
            node_list.append(n[0])
            if n in path:
                node_color_array.append(ncolors['path'])
            else:
                node_color_array.append(ncolors[n[1]['type']])

        edges = self.G.edges(data=True)
        edge_list = list()
        edge_color_array = list()
        for e in edges:
            edge_list.append((e[0], e[1]))
            edge_color_array.append(ecolors['start'])

        nx.draw_networkx(self.G,
                         pos=nx.get_node_attributes(self.G, 'data'),
                         width=0.7,
                         edge_list=edge_list,
                         edge_color=edge_color_array,
                         node_list=node_list,
                         node_color=node_color_array,
                         node_size=160,
                         fontsize=8,
                         ax=ax)

    def _check_node_attributes(self, node_id, attribute):
        assert attribute in self._node_attrs,\
            'Attribute [{}] is invalid | Expected:{}'\
            .format(attribute, self._node_attrs)
        assert node_id in self.nodes, \
            'Node ({}) not in the graph'.format(node_id)

    def _check_edge_attributes(self, source, target, attribute):
        assert attribute in self._edge_attrs, \
            'Attribute [{}] is invalid | Expected:{}'\
            .format(attribute, self._edge_attrs)
        assert self.G.has_edge(source, target),\
            'Edge [{}-{}] does not exist in the graph'.format(source, target)

    @property
    def G(self):
        return self._graph

    @property
    def nodes(self):
        return self.G.nodes()

    @property
    def nodes_data(self):
        return self.G.nodes(data=True)

    @property
    def all_edges(self):
        return self.G.edges()

    @property
    def transition_matrix(self):
        """ Get the transition matrix T(s, a, s')

        Obtained from the adjacency matrix of the underlying graph

        """
        return nx.adjacency_matrix(self.G).todense()


def eud(data1, data2):
    return sqrt((data1[0]-data2[0])**2 + (data1[1]-data2[1])**2)

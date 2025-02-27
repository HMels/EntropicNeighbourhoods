# -*- coding: utf-8 -*-
"""
Created on Thu Mar  9 19:48:13 2023

@author: Mels
"""

import tensorflow as tf
import matplotlib.pyplot as plt
import numpy as np
import random
from matplotlib.patches import Polygon as PolygonPatch
import time

tf.config.run_functions_eagerly(True)  ### TODO should be False
plt.close('all')

from inputData import InputData
from communities import Communities
from optimizationData import OptimizationData

class ModelGeo(InputData, tf.keras.Model):
    def __init__(self, InputData, N_communities: int):
        """
        Initializes the Dataset object with given socioeconomic data, population size, number of communities, and neighbourhood locations.
    
        Args:
            InputData : InputData Class
                (InputData.N x N_features) array containing the socioeconomic data of the initial neighbourhoods.
            N_communities : The number of communities to end up with.
    
        Raises:
            Exception: If the number of new communities is greater than the number of neighbourhoods.
    
        Attributes:
            InputData.Socioeconomic_data : TensorFlow
                (InputData.N x 1 x 1) TensorFlow variable containing the socioeconomic data of the initial neighbourhoods.
            InputData.Population : TensorFlow
                (InputData.N x 1 x 1) TensorFlow variable containing the population sizes of the initial neighbourhoods.
            InputData.Locations : TensorFlow
                (InputData.N x 2) TensorFlow variable containing the grid locations of the initial neighbourhoods.
            Communities.N : int
                The number of communities to end up with.
            InputData.N : int
                The number of initial neighbourhoods.
            Map : Tensor
                (Communities.N x InputData.N) TensorFlow variable representing the community map.
            Communities.Locations : Variable
                (Communities.N x 2) TensorFlow variable representing the center points of the new communities.
            population_bounds : Variable
                (2,) TensorFlow variable representing the upper and lower boundaries by which the population can grow or shrink of their original size.
            tot_pop : Tensor
               TensorFlow tensor representing the total population size of all initial neighbourhoods.
            avg_pop : Tensor
                TensorFlow tensor representing the average population size of the initial neighbourhoods.
            popBoundHigh : Tensor
                TensorFlow tensor representing the upper population boundary for the new communities.
            popBoundLow : Tensor
                TensorFlow tensor representing the lower population boundary for the new communities
        """

        #super(Dataset, self).__init__()
        tf.keras.Model.__init__(self)
        
        ## TODO delete the optimizer, it isn't being used
        
        # dataset should have the next variables: 
        #    neighbourhoods (numpy.ndarray): A 1D array of strings containing the names of the neighbourhoods.
        #    Population (numpy.ndarray): A 1D array of floats containing the number of private Population in each neighbourhood.
        #    Socioeconomic_data (numpy.ndarray): A 1D array of floats containing the socio-economic value of each neighbourhood.
        #    Locations (numpy.ndarray): A numpy array of shape (n,2) containing the mapped coordinates.
        self.InputData = InputData
        self.Socioeconomic_data = InputData.Socioeconomic_data
        self.GeometryNeighbours = None
        
        if self.InputData.Locations is None:
            Exception('DataLoader has not initialised neighbourhood locations yet. Use the function DataLoader.map2grid(latlon0) to do this!')
        
        
        # Initialize communities
        self.Communities = Communities(N_communities)
        try:
            self.Communities.initialize_community_Locations(self.Communities.N, self.InputData.wijk_centers)
        except:
            self.Communities.initialize_community_Locations(self.Communities.N, self.InputData.Locations)
        
        # Initialize the distance matrix and the economic values
        self.initialize_distances()


    def initialise_optimisation(self, weights: list = [8,35,30,35], LN: list = [1,2,2,3], N_iterations: int = 50, 
                            population_bounds: list = [0.9, 1.1]):  
        '''
        Initialises the optimisation algorithm.
    
        Parameters
        ----------
        weights : A list of the weights. Respectively, SESvariance, PopBounds, distance. Default is [8,35,30,35].
        LN : The regularization N powers. Respectively, SESvariance, PopBounds, distance. Default is [1,2,2,3].
        N_iterations : Number of iterations to run the optimizer. Default is 50.
        population_bounds : The upper and lower population bounds for each community. Default is [0.9, 1.1].
        '''

        # initialise weights
        # ORDER OF WEIGHTS: SES variance, Pop bounds, Distance, Education
        self.OptimizationData = OptimizationData(weights=weights, N_iterations=N_iterations, LN=LN)
        
        # Initialize population parameters
        self.tot_pop = tf.reduce_sum(self.InputData.Population)
        self.avg_pop = self.tot_pop / self.Communities.N # Average population size
        self.OptimizationData.initialize_popBoundaries(self.avg_pop, population_bounds=population_bounds)
        
        # costs initialization 
        self.initialize_norm()
        self.cost_fn()
        self.OptimizationData.storeCosts()
        self.OptimizationData.printCosts(text="Initial state of Costs:")  
        
    
    @property
    def mapped_Education_population(self):
        # The education level per Community in people
        return self(self.InputData.Education_population)  
        
    @property
    def mapped_Education(self):
        # The education level per Community
        return tf.multiply(self.mapped_Education_population, 
                           tf.expand_dims(1/self.mapped_Population, axis=1)) * 100
    
    @property
    def mapped_Population(self):
        # The population per Community
        return self(self.InputData.Population)
    
    @property
    def mapped_Socioeconomic_data(self):
        # the Socioeconomic data per Community
        #return self(self.InputData.Socioeconomic_population)/self.mapped_Population
        return self(self.Socioeconomic_data) / self.numBuurtenInCommunities
    
    @property
    def population_Map(self):
        # the Map (as Communities.N x InputData.N Tensor) filled with populations
        return tf.round(self.Map(self.InputData.Population))
    
    @property
    def neighbourhood_Map(self):
        # the Map (as Communities.N x InputData.N Tensor) filled with ones to map the neighbourhoods
        return self.Map(tf.ones(self.InputData.N))
    
    @property
    def mean_distances(self):
        return tf.reduce_mean( self.distances * self.neighbourhood_Map , axis=1)
    
    @property
    def numBuurtenInCommunities(self) -> np.ndarray:
        '''
        Counts the number of neighborhoods in each community.
    
        Returns
        -------
        np.ndarray
            An array containing the number of neighborhoods in each community.
        '''

        counts = tf.zeros((self.Communities.N,), dtype=tf.int32)
        for i in range(self.Communities.N):
            label_count = tf.reduce_sum(tf.cast(tf.equal(self.labels, i), tf.int32))
            counts = tf.tensor_scatter_nd_add(counts, [[i]], [label_count])
    
        return counts.numpy()
    
    @tf.function
    def applyMapCommunities(self):
        self.Communities.Population = self.mapped_Population
        self.Communities.Socioeconomic_data = self.mapped_Socioeconomic_data
        self.Communities.Education = self.mapped_Education
        
        
        
    @tf.function
    def Map(self, inputs, labels=None):
        '''
        Creates a Map of the inputs according to the labels

        Parameters
        ----------
        inputs : (InputData.N) or (InputData.N x 2) Tensor
            The inputs that we want to be transformed into a Map Tensor.

        Raises
        ------
        Exception
            If the length of inputs and labels are not equal.

        Returns
        -------
        (Communities.N x InputData.N) or (Communities.N x InputData.N x 2) Tensor
            The Mapped output
        '''
        if labels is None:
            if tf.squeeze(inputs).shape[0]!=self.labels.shape[0]: 
                raise Exception("inputs should have the same lenght as self.labels!")
            indices = tf.transpose(tf.stack([self.labels, tf.range(self.InputData.N)]))
            if len(tf.squeeze(inputs).shape)==2:
                return tf.scatter_nd(indices, tf.squeeze(inputs), shape =
                                     (self.Communities.N, self.InputData.N, tf.squeeze(inputs).shape[1]))
            else:
                return tf.scatter_nd(indices, tf.squeeze(inputs), shape = (self.Communities.N, self.InputData.N))
            
        else: # in the case we give a different map        
            if tf.squeeze(inputs).shape[0]!=labels.shape[0]: 
                raise Exception("inputs should have the same lenght as self.labels!")
            indices = tf.transpose(tf.stack([labels, tf.range(self.InputData.N)]))
            if len(tf.squeeze(inputs).shape)==2:
                return tf.scatter_nd(indices, tf.squeeze(inputs), shape = (self.Communities.N, self.InputData.N, 2))
            else:
                return tf.scatter_nd(indices, tf.squeeze(inputs), shape = (self.Communities.N, self.InputData.N))
        
    
    @tf.function
    def call(self, inputs: tf.Tensor) -> tf.Tensor:
        '''
        Transforms the inputs according to the label.
    
        Parameters
        ----------
        inputs : The inputs to be transformed. It can be of shape (InputData.N) or (InputData.N x 2).
    
        Returns
        -------
        The transformed values of the tensor. It can be of shape (Communities.N) or (Communities.N x 2).
        '''
        return tf.reduce_sum(self.Map(inputs), axis=1)
    

    @tf.function
    def cost_fn(self) -> tf.Tensor:
        """
        Calculates the cost function that needs to be minimized during the optimization process. The cost function consists of several
        regularization terms that encourage the population map to have certain properties, such as positive values and limits on population
        growth.
        
        Returns:
        tf.float32: A float representing the sum of all partial costs.
        
        Raises:
        ValueError: If the shape of any TensorFlow tensor used in the cost function is not as expected.
        
        Attributes:
        OptimizationData.weight_SESvariance (float):
        The weight given to the variance of the socioeconomic data mapped to the population map.
        OptimizationData.weight_popPositive (float):
        The weight given to the regularization term that ensures the population map is positive.
        OptimizationData.weight_popBounds (float):
        The weight given to the regularization term that limits the growth or shrinkage of population within a certain range.
        tot_pop (Tensor):
        A TensorFlow tensor representing the total population size of all initial neighbourhoods.
        max_distance (float):
        The maximum distance between two communities in the community map.
        OptimizationData.weight_distance (float):
        The weight given to the regularization term that penalizes communities that are too far apart.
        
        Returns:
        Tensor: A TensorFlow tensor representing the sum of all partial costs.
        """        
        # Calculate variance of socioeconomic data mapped to population map
        SES_variance = tf.math.reduce_variance( self.mapped_Socioeconomic_data )
    
        # Regularization term for population limits
        cost_popBounds = tf.math.reduce_variance(self.mapped_Population)
        
        # Add regularization term based on distances
        cost_distance = self.cost_distances()
        
        # Add varience in education mapped_Education_population
        education_variance = tf.math.reduce_mean(tf.math.reduce_variance( self.mapped_Education, axis=0 ))
        
        # Input costs into the OptimizationData model and save them
        self.OptimizationData.saveCosts(SES_variance, cost_popBounds, cost_distance, education_variance)
        return self.OptimizationData.totalCost
    
    
    @tf.function
    def refine(self, Nit: int, temperature: float=0) -> tf.Tensor:
        """
        Refines a labeling of a set of points using the Potts model, minimizing a cost function.
    
        Parameters
        ----------
        Nit : The number of iterations to run the refinement algorithm.
        temperature : The temperature parameter of the Potts model, controlling the degree of smoothing.
            The default value is 1.2.
    
        Returns
        -------
        A tensor of shape (N,), where N is the number of points in the set. The tensor
            contains the updated labels for each point, after the refinement algorithm.
    
        Description
        -----------
        This method refines a labeling of a set of N points using the Potts model. The
        algorithm proceeds by iteratively updating the label of each point, one at a time,
        while keeping the labels of all other points fixed. The goal of the refinement 
        algorithm is to find a labeling that minimizes the cost function. The algorithm 
        is run for a fixed number of iterations, specified by the Nit parameter. At each
        iteration, the temperature parameter is decreased by a factor of 0.99, to gradually
        reduce the smoothing and focus the algorithm on finding more precise solutions.
        The cost function used by the algorithm is specified by the cost_fn method of the
        self object. During the algorithm, the cost of each labeling is stored in the
        OptimizationData object associated with the self object.
        """
        
        # load neigbhours
        if self.GeometryNeighbours is not None: 
            self.GeometryNeighbours = self.InputData.find_polygon_neighbours()
            
        t = time.time()
        for i in range(Nit):
            # iterate over the neighbourhoods 
            labelslist = list(range(self.InputData.N))
            random.shuffle(labelslist)
            for label in labelslist:
                label_old = self.labels[label]
                label_cost = self.cost_fn()
                
                # iterate over the neighbours to 
                neighbours = self.GeometryNeighbours[label]
                random.shuffle(neighbours)
                labellist_tried=[] # list of labels that have been tried already
                for neighbour in neighbours:
                    # check if label is not the same or hasn't been tried before
                    if ( self.labels[neighbour] != self.labels[label] and
                        self.labels[neighbour] not in labellist_tried):
                        
                        self.labels[label].assign(self.labels[neighbour])
                        labellist_tried.append(self.labels[label].numpy())                            
                        neighbour_cost = self.cost_fn()
                        
                        # if the new labeling breaks the communities in two, don't do this
                        if (label_old in tf.unique(self.labels)[0].numpy() and 
                            not self.check_connected(label_old)):
                            #if not self.check_connected(label_old):
                            self.labels[label].assign(label_old)
                            break
                        '''
                        # checks if a community is not deleted
                        if len(tf.unique(self.labels)[0])!=self.Communities.N:
                            self.labels[label].assign(label_old)
                            break
                        '''##TODO fix this
                        # choose to accept or reject
                        if neighbour_cost < label_cost:
                            label_cost = neighbour_cost
                                                        
                        else:
                            # Calculate the probability of accepting a higher-cost move
                            delta = neighbour_cost - label_cost
                            prob_accept = tf.exp(-delta / temperature)
                            # Accept the move with probability prob_accept
                            if random.uniform(0, 1) < prob_accept:
                                label_cost = neighbour_cost
                            else:
                                self.labels[label].assign(label_old)
                                
                                
            self.OptimizationData.storeCosts()   
            if i % 10 == 0:
                # Print current loss and individual cost components
                print("Time passed = "+str(int((time.time()-t)//60))+"min "+str(round(time.time()-t)%60)+"sec")
                print("Step: {}, Loss: {}".format(i, label_cost.numpy()))
                self.OptimizationData.printCosts()
                t = time.time()
                
            temperature *= 0.99
        return self.labels
    
    
    def check_connected(self, label: int) -> bool:
        """
        Check if all objects with the same label are connected via Depth First Search (DFS).
        
        The algorithm maintains a stack to keep track of the nodes that still need to be
        explored. When a node is visited, its adjacent nodes are added to the stack, and 
        the algorithm continues exploring the next node on the stack. This process continues
        until all reachable nodes have been visited, or until a goal node has been found.
    
        Parameters
        ----------
        label : The label to check for connectivity.
    
        Returns
        -------
        True if all objects with the same label are connected, False otherwise.
        """
        # Get indices of objects with given label
        indices = tf.where(tf.equal(self.labels, label))
    
        # Initialize set of visited objects and stack for DFS
        visited = set()
        stack = [tuple(indices[0].numpy())]
    
        # Do DFS to visit all objects with the same label
        while stack:
            i = stack.pop()
            if i not in visited:
                visited.add(i)
                # Add unvisited neighbours to stack
                neighbours = self.GeometryNeighbours[i]
                for ni in neighbours:
                    if ni not in visited and self.labels[ni] == label:
                        stack.append((ni,))
    
        # Check if all objects with the same label have been visited
        return len(visited) == len(indices)
    
    
    @tf.function
    def initialize_norm(self):
        # Normalizes the weights such that relatively all costs start at 1. 
        # Then it multplies the normalized weights by the assigned weights
        self.OptimizationData.norm_SESvariance = tf.math.reduce_variance( self.mapped_Socioeconomic_data ) 
        self.OptimizationData.norm_distance = self.cost_distances()
        self.OptimizationData.norm_education = tf.math.reduce_mean( tf.math.reduce_variance( self.mapped_Education, axis=0 ) )
        self.OptimizationData.norm_popBounds = tf.math.reduce_variance(self.mapped_Population)
        
        
    @tf.function
    def cost_distances(self):
        '''
        calculates the costs of distances by averaging out all the distances per Community

        Raises
        ------
        Exception
            If the distances have not been initialised yet.

        Returns
        -------
        TensorFlow.float32
            The costs of the current distances.

        '''
        try: self.distances
        except: raise Exception("Distances have not been initialised yet!")
        return tf.reduce_sum(self.mean_distances)
        
        
    @tf.function
    def initialize_distances(self) -> tf.float32:
        """
        Initializes the pairwise distances between the newly created communities and the initial neighbourhoods.

        Parameters:
        -----------
        InputData.Locations: tf.float32 Tensor
            A tensor of shape (InputData.N, 2) containing the grid locations of the initial neighbourhoods.
        Communities.Locations: tf.float32 Tensor
            A tensor of shape (Communities.N, 2) containing the grid locations of the newly created communities.

        Returns:
        --------
        distances: tf.float32 Tensor
            A tensor of shape (InputData.N, Communities.N) containing the differences in distance between all indices.
        max_distance: tf.float32 scalar
            The maximum distance between any two locations.
        
        Raises:
        -------
        ValueError: If the shape of Locations or Communities.Locations is not as expected.
        """
        # Repeat the rows of Locations M times and the rows of Communities.Locations N times
        InputLocations_repeated = tf.repeat(tf.expand_dims(self.InputData.Locations, axis=0), self.Communities.N, axis=0)
        CommunitiesLocations_repeated = tf.tile(tf.expand_dims(self.Communities.Locations, axis=1), [1, self.InputData.N, 1])
    
        # Calculate the pairwise distances between all pairs of locations using the Euclidean distance formula
        self.distances = tf.sqrt(tf.reduce_sum(tf.square(InputLocations_repeated - CommunitiesLocations_repeated), axis=-1))
        self.max_distance = tf.reduce_max(self.distances)
        
        # now for all distances
        InputLocations_repeated = tf.repeat(tf.expand_dims(self.InputData.Locations, axis=0), self.InputData.N, axis=0)
        self.all_distances = tf.sqrt(tf.reduce_sum(tf.square(InputLocations_repeated - tf.transpose(InputLocations_repeated, perm=[1,0,2])), axis=-1))
        return self.distances
    
    
    def initialize_labels(self) -> tf.Variable:
        '''
        Initialised the labels via an algorithm that lets the communities spread out like a virus:
            1. The neighbourhoods closest to the community centers will be initialised
                as those communities. The rest will be initiated with a New Label
            2. The model iterates over the communities and the adjecent neighbours of 
                those communities
                2.1. The model calculates which new neighbour (that is not part of another community)
                    would result in the SES value getting closer to the average SES
                2.2. The model chooses That neighbour and adds its values to the communities
                2.3. The model deletes neigbours of communities that are already part of said commynity
                2.4. The model evaluates if there are any neighbourhoods that are not part of 
                    Communities
                2.5. If not, the model stops. Else it will iterate further
                
                ## TODO add the new code here. About force quiting!

        Raises
        ------
        Exception
            If the distances have not been initialised.

        Returns
        -------
        tf.Variable int  
            The newly calculated labels that map the neighbourhoods to their Communities.

        '''
        try: self.distances
        except: raise Exception("Distances should be initialized before running this function!")
        
        labels = [None for _ in range(self.InputData.N)]
        self.GeometryNeighbours = self.InputData.find_polygon_neighbours()
        
        # create the basis of the communities. The initial neighbours from which the communities spread out
        index = tf.argmin(self.distances, axis=1)
        com_Neighbours=[]       # the neighbours of the communities in the current state
        com_SES=[]              # the SES value of the communities in the current state
        com_index=[]            # the indices of neighbourhoods in the current communities
        for i in range(self.Communities.N):
            labels[index[i]]=i
            com_Neighbours.append(list(self.GeometryNeighbours[index[i]]))
            #com_SES.append(self.InputData.Socioeconomic_population[index[i]].numpy())
            com_SES.append(self.Socioeconomic_data[index[i]].numpy())
            com_index.append([index[i].numpy()])        
                    
        # let the communities spread out to nearest neighbours
        #avg_SES = tf.reduce_mean(self.InputData.Socioeconomic_population)
        avg_SES = tf.reduce_mean(self.Socioeconomic_data)
        iteration_stuck = 0
        none_indices_old = []
        while True:
            # iterate over the communities randomly and load their current values
            Coms = list(range(self.Communities.N))
            random.shuffle(Coms)
            for i in Coms:             
                # calculate the SES values of of adding the neighbourhoods to the list 
                SES_current = tf.reduce_sum(tf.gather(self.Socioeconomic_data, com_index[i]))
                SES_neighbour = tf.gather(self.Socioeconomic_data, com_Neighbours[i])
                SES_option=(np.abs((SES_current + SES_neighbour - avg_SES).numpy()))
                    
                # choose the best SES value
                index_decision=None
                for j in range(len(SES_option)): 
                    option = com_Neighbours[i][np.argsort(SES_option)[j]]
                    if labels[option] is None: # Neighbourhood should not be part of community already
                        index_decision=option
                        break
                    
                # if no index has been found, move on
                if index_decision is None: continue 
                if index_decision in com_index: raise Exception("The index_decision is already part of the community!")
                
                # in case all neighbours are already taken add the newly decided values to the community
                if labels[index_decision] is None: 
                    labels[index_decision] = i
                    com_Neighbours[i] += list(self.GeometryNeighbours[index_decision])
                    com_SES[i] +=  tf.gather(self.Socioeconomic_data, index_decision).numpy()
                    com_index[i].append(index_decision)
                    
                # delete neighbours that are within the community
                for nghb_i in range(len(com_Neighbours[i])-1, -1, -1):
                    if com_Neighbours[i][nghb_i] in com_index:
                        com_Neighbours[i].pop(nghb_i)
                            
            count = 0
            for label in labels:
                if label is None:
                    count+=1
            if count == 0: break
        
            # see if the model has gotten stuck
            none_indices_new = [i for i, label in enumerate(labels) if label is None]
            if none_indices_new == none_indices_old:
                iteration_stuck+=1
                if iteration_stuck==50: # after 50 iterations  of nothing happening, force exit
                    print("PROGRAM GOT STUCK: FORCE EXIT!") 
                    print("During initialization of labels, "+str(len(none_indices_new))+" labels where not initialized.")
                    print("They will now be initialized according to their nearest neighbours label.")
                    time.sleep(3)
                    for index in none_indices_new: # copy the label from its neighbour
                        for index_nghb in com_Neighbours[i]:
                            if labels[index_nghb] is not None:    
                                labels[index]=labels[index_nghb]
                    break
            else: 
                iteration_stuck=0
            none_indices_old = none_indices_new
        
        self.labels = tf.Variable(labels)   
        self.applyMapCommunities()         
        return self.labels
    
    
    def initialize_labels_random(self):
        '''
        Initialise  the labels via a random algorithm

        Raises
        ------
        Exception
            If the distances have not been initialised.

        '''
        try: self.distances
        except: raise Exception("Distances should be initialized before running this function!")
        
        labels = [None for _ in range(self.InputData.N)]
        self.GeometryNeighbours = self.InputData.find_polygon_neighbours()
        
        # create the basis of the communities. The initial neighbours from which the communities spread out
        index = tf.argmin(self.distances, axis=1)
        com_Neighbours=[]       # the neighbours of the communities in the current state
        com_index=[]            # the indices of neighbourhoods in the current communities
        for i in range(self.Communities.N):
            labels[index[i]]=i
            com_Neighbours.append(list(self.GeometryNeighbours[index[i]]))
            com_index.append([index[i].numpy()])        
                    
        # let the communities spread out to nearest neighbours
        iteration_stuck = 0
        none_indices_old = []
        while True:
            # iterate over the communities randomly and load their current values
            Coms = list(range(self.Communities.N))
            random.shuffle(Coms)
            for i in Coms:                
                # choose a random index
                index_decision=None
                current_com_ngbhrs = com_Neighbours[i]
                random.shuffle(current_com_ngbhrs)
                for option in current_com_ngbhrs: 
                    if labels[option] is None: # take the first random index that is not taken yet
                        index_decision=option
                        break
                    
                # if no index has been found, move on
                if index_decision is None: continue 
                if index_decision in com_index: raise Exception("The index_decision is already part of the community!")
                
                # in case all neighbours are already taken add the newly decided values to the community
                if labels[index_decision] is None: 
                    labels[index_decision] = i
                    com_Neighbours[i] += list(self.GeometryNeighbours[index_decision])
                    com_index[i].append(index_decision)
                    
                # delete neighbours that are within the community
                for nghb_i in range(len(com_Neighbours[i])-1, -1, -1):
                    if com_Neighbours[i][nghb_i] in com_index:
                        com_Neighbours[i].pop(nghb_i)
                        
                            
            count = 0
            for label in labels:
                if label is None:
                    count+=1
            if count == 0: break
        
            # see if the model has gotten stuck
            none_indices_new = [i for i, label in enumerate(labels) if label is None]
            if none_indices_new == none_indices_old:
                iteration_stuck+=1
                if iteration_stuck==50: # after 50 iterations  of nothing happening, force exit
                    print("PROGRAM GOT STUCK: FORCE EXIT!") 
                    print("During initialization of labels, "+str(len(none_indices_new))+" labels where not initialized.")
                    print("They will now be initialized according to their nearest neighbours label.")
                    time.sleep(3)
                    for index in none_indices_new: # copy the label from its neighbour
                        for index_nghb in com_Neighbours[i]:
                            if labels[index_nghb] is not None:    
                                labels[index]=labels[index_nghb]
                    break
            else: 
                iteration_stuck=0
            none_indices_old = none_indices_new
        
        self.labels = tf.Variable(labels)   
        self.applyMapCommunities()         
        return self.labels
    
    
    def plot_communities(self,cdict=None, extent=None, print_labels=False, title='Communities After Optimization'):
        def create_color_dict(N: int) -> dict:
            """
            Creates a dictionary of colors with RGB values that are evenly spaced.
            
            Parameters:
            - N (int): The number of colors to generate.
            
            Returns:
            - colors_dict (dict): A dictionary of colors with keys ranging from 0 to N-1 and values in the format
                                  recognized by matplotlib.pyplot.
            """
            cmap = plt.cm.get_cmap('gist_rainbow', N)  # Get a colormap with N colors
            
            colors_dict = {}
            for i in range(N):
                rgb = cmap(i)[:3]  # Extract the RGB values from the colormap
                color = np.array(rgb) * 255  # Convert the RGB values from [0, 1] to [0, 255]
                colors_dict[i] = '#{:02x}{:02x}{:02x}'.format(*color.astype(int))  # Convert the RGB values to hex format
            
            return colors_dict
        
        if cdict is None:
            cdict = create_color_dict(self.Communities.N)
        
        
        # Reload colors
        colour = []
        for label in self.labels.numpy():
            colour.append(cdict[label])
            
        if extent is None:
            geominx = min(self.InputData.GeometryGrid[0].exterior.xy[0])
            geomaxx = max(self.InputData.GeometryGrid[0].exterior.xy[0])
            geominy = min(self.InputData.GeometryGrid[0].exterior.xy[1])
            geomaxy = max(self.InputData.GeometryGrid[0].exterior.xy[1])
            for polygon in self.InputData.GeometryGrid:
                geominx = min( [min(polygon.exterior.xy[0]), geominx] )
                geomaxx = max( [max(polygon.exterior.xy[0]), geomaxx] )
                geominy = min( [min(polygon.exterior.xy[1]), geominy] )
                geomaxy = max( [max(polygon.exterior.xy[1]), geomaxy] )
            extent = [geominx-200, geomaxx+200, geominy-200, geomaxy+200]
                        
        # Create plot
        fig, ax = plt.subplots(figsize=(5, 4))   
        for i, polygon in enumerate(self.InputData.GeometryGrid):
            patch = PolygonPatch(np.array(polygon.exterior.xy).T, facecolor=colour[i], alpha=0.5)
            ax.add_patch(patch)
                
        if print_labels:
            colors = [cdict[i] for i in range(self.Communities.N)]
            x, y = np.meshgrid(extent[1]*12/16, np.linspace(extent[2]+(extent[3]-extent[2])*2/4,
                                                          extent[2]+(extent[3]-extent[2])*15/16, self.Communities.N))
            ax.scatter(x, y, s=self.Communities.Population/100, c=colors, alpha=.8, ec='black')
            for i, txt in enumerate(np.round(self.Communities.Socioeconomic_data.numpy(), 3)):
                ax.annotate(txt, (x[i]+80, y[i]-80), fontsize=10)
    
        ax.set_xlim(extent[0],extent[1])
        ax.set_ylim(extent[2],extent[3])
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(title)
        return fig, ax
    
    
    @tf.function
    def print_summary(self):
        print(
          "\nThe Labels are:\n",self.labels.numpy(),
          "\n\nThe Population Map is:\n",tf.round( self.population_Map.numpy()),
          "\n\nSocioeconomic_data:\n", tf.expand_dims(self.mapped_Socioeconomic_data, axis=1).numpy(),
          "\n\nPopulation Size:\n", tf.round( tf.expand_dims(self.mapped_Population, axis=1) ).numpy()
          #,"\n\n",
          #"The Variances are:\n",
          #"Population: "+tf.math.reduce_variance(self.mapped_Population),
          #"\n Socioeconomic_data: "+tf.math.reduce_variance(self.mapped_Socioeconomic_data),
          #"\nEducation Levels: "+tf.math.reduce_variance( self.mapped_Education, axis=0 ),
          #"\n\nThe mean distance equals: "+self.mean_distances          
          )
        
        
# -*- coding: utf-8 -*-
"""
Created on Wed Mar  8 19:12:20 2023

@author: Mels

This is a Python script that defines a class called InputData. It has methods to 
reload data from a new CSV file and to map the geospatial data to a regular grid. 
The class also includes several attributes, such as neighbourhoods, Socioeconomic_data,
 Population, Locations, N, center_coordinates, and gdf, which store the loaded data in 
 various formats such as NumPy arrays, TensorFlow Tensors, and geopandas dataframes.
"""

import pandas as pd
import geopandas as gpd
import numpy as np
from geopy import distance
import tensorflow as tf
from shapely.geometry import Polygon, MultiLineString, MultiPoint


class InputData:
    def __init__(self, path: str, buurtenOnOff: bool = True):
        """
        Initializes an instance of the class and loads socio-economic data from a CSV file.
    
        Args:
            path : The path to the CSV file containing the socio-economic data.
            buurtenOnOff : True if you only need to load the buurten, False if you need wijken. Default is True.
    
        Raises:
            FileNotFoundError: If the specified file path does not exist.
    
        Notes:
            The CSV file must have columns separated by semicolons and enclosed in quotes.
            Rows with missing or invalid data are removed from the loaded data.
    
        Attributes:
            neighbourhoods : array
                1D array of strings containing the names of the neighbourhoods.
            Population : Tensor
                1D TensorFlow Tensor of floats containing the number of private Population in each neighbourhood.
            Socioeconomic_data : Tensor
                1D TensorFlow Tensor of floats containing the socio-economic value of each neighbourhood.
        """
        # Load data from CSV file using pandas
        data = pd.read_csv(path, delimiter=';', quotechar='"', na_values='       .')
        
        # Replace '       .' with NaN in columns 3 and 4 and delete these rows as they don't have data data
        data = data.replace('       .', float('nan'))
        data.dropna(inplace=True)
        data = data.values

        # Extract relevant variables and store as class variables
        self.neighbourhoods = data[:,1]  # neighbourhood names
        self.neighbourhood_codes = data[:,2]  # neighbourhood codes
        self.Population = tf.Variable(np.array(data[:,3].tolist()).astype(np.float32)[:],
                                      trainable=False, dtype=tf.float32) # Number of households per neighbourhood
        self.Education = tf.transpose(tf.Variable([data[:,4], data[:,5], data[:,6]],
                                                  trainable=False, dtype=tf.float32)) # education levels Low, Medium, High
        self.Socioeconomic_data = tf.Variable(np.array(data[:,7].tolist()).astype(np.float32)[:],
                                              trainable=False, dtype=tf.float32) # Socio-economic value of the region
        
        # data yet to be loaded
        self.Locations = None      
        self.GeometryGrid = None
        self.Geometry = None
        
        self.N = self.Socioeconomic_data.shape[0]
        
        # filter buurtcodes that don't start with BU
        indices = []
        self.buurten_in_wijken = []
        self.buurtenOnOff = buurtenOnOff
        marker="BU" if self.buurtenOnOff else "WK"
        for i, codes in enumerate(self.neighbourhood_codes):
            if codes[:2]==marker:
                indices.append(i)
            # we will loop over the following buurten and add their codes such that we know which
            # buurten belong to which wijken
            if codes[:2]=="WK":
                j=i+1
                buurten_in_wijken = []
                while True:
                    if j==self.N or self.neighbourhood_codes[j][:2]=="WK": break
                    if self.neighbourhood_codes[j][:2]=="BU":
                        buurten_in_wijken.append(self.neighbourhood_codes[j])
                    j+=1
                if len(buurten_in_wijken)!=0:
                    self.buurten_in_wijken.append(buurten_in_wijken)
                
        self.gather(indices)
     
        
    @property
    def Education_population(self):
        # returns a tf.float32 
        # The Education data multiplied by the population to get the actual socioeconomic value.
        return tf.multiply(self.Education/100, tf.expand_dims(self.Population, axis=1))
        
    
    def gather(self, indices: list):
        '''
        Gathers the indices inputted for all properties 
        '''
        if len(indices)==0: raise Exception("No indices inputted to be gathered")
        
        neighbourhoods=[]
        neighbourhood_codes=[]
        Population=[]
        Education=[]
        Socioeconomic_data=[]
        for i in indices:
            neighbourhoods.append(self.neighbourhoods[i])
            neighbourhood_codes.append(self.neighbourhood_codes[i])
            Population.append(self.Population[i].numpy())
            Education.append(self.Education[i].numpy())
            Socioeconomic_data.append(self.Socioeconomic_data[i].numpy())
                
        self.neighbourhoods = neighbourhoods
        self.neighbourhood_codes = neighbourhood_codes
        self.Population = tf.Variable(Population, trainable=False, dtype=tf.float32)#tf.gather(self.Population, indices)
        self.Education = tf.Variable(Education, trainable=False, dtype=tf.float32)#tf.gather(self.Education, indices)
        self.Socioeconomic_data = tf.Variable(Socioeconomic_data, trainable=False, dtype=tf.float32)#tf.gather(self.Socioeconomic_data, indices)        
        
        ##TODO add neighbours here if initiated
        
        
    def load_miscData(self, path: str):
        """
        Loads the miscalenous data from the file that can be downloaded from  
        https://www.cbs.nl/nl-nl/maatwerk/2011/48/kerncijfers-wijken-en-buurten-2011

        """
        # read in the file using pandas
        dtypes = {'GM_CODE': str, 'WK_CODE': str, 'BU_CODE': str}
        df = pd.read_excel(path, dtype=dtypes)
        
        # iterate over the neighbourhood codes list and extract the rows corresponding to each neighbourhood
        dfs = []
        for code in self.neighbourhood_codes:
            gm_code = code[2:6]
            wk_code = code[6:8]
            bu_code = code[8:]
            df_neighbourhood = df[(df['RECS'] == 'Buurt') &
                                  (df['GM_CODE'] == gm_code) &
                                  (df['WK_CODE'] == wk_code) &
                                  (df['BU_CODE'] == bu_code)]
            if len(df_neighbourhood)==0:
                print(code,"Not found")
            dfs.append(df_neighbourhood)
        
        # concatenate the dataframes and select the columns you're interested in
        df_final = pd.concat(dfs)
        pop_sex = df_final[['AANT_MAN', 'AANT_VROUW']]
        pop_age = df_final[['P_00_14_JR', 'P_15_24_JR', 'P_25_44_JR', 'P_45_64_JR', 'P_65_EO_JR']]

        # convert the selected columns to arrays
        self.pop_sex = tf.Variable(pop_sex.to_numpy(), dtype=tf.int32, trainable=False)
        self.pop_age = tf.Variable(pop_age.to_numpy(), dtype=tf.int32, trainable=False)   
        
        
    def load_wijken_centers(self):
        '''
        Loads all the buurten in a wijk (via the variable buurten_in_wijken) and then 
        calculates the average center_coordinates of that wijk
        '''
        try: self.Coordinates
        except: raise Exception("First load the center coordinates and other geographical data via self.load_geo_data!")
        
        wijk_centers=[]
        neighbourhood_codes=tf.Variable(self.neighbourhood_codes)
        for wijk_codes in self.buurten_in_wijken:
            centerx, centery = 0,0
            counter=0
            for buurt_codes in wijk_codes:
                i = tf.where(neighbourhood_codes==buurt_codes)
                if len(i)!=0 and len(self.Coordinates[i[0][0]])==2:
                    centers=self.Coordinates[i[0][0]].numpy()
                    centerx+=centers[0]
                    centery+=centers[1]
                    counter+=1
            if counter!=0: #check if buurten have been loaded
                wijk_centers.append(np.array([centerx,centery])/counter)
        self.wijk_centers=tf.Variable(wijk_centers)
            
        
    
    def load_geo_data(self, filename):
        """
        Loads geospatial data from a specified file in geopackage format and stores it in the class variables. 
    
        Args:
            filename: The path to the geopackage file containing the geospatial data.
    
        Returns:
            None
    
        Raises:
            FileNotFoundError: If the specified file path does not exist.
    
        Notes:
            This function uses the geopandas library to read a geopackage file specified by `filename`. It then 
            converts the spatial reference system to 'EPSG:4326', explodes the multipolygons into polygons and 
            converts the polygons to center coordinates. The center coordinates are stored in the `center_coordinates`
            class variable as a numpy array, while the original geopandas dataframe is stored in the `gdf` class variable.
            The CSV file must have columns separated by semicolons and enclosed in quotes.
    
        Attributes:
            center_coordinates (numpy.ndarray): A 2D numpy array of shape (n, 2), where n is the number of polygons
            in the geopackage file. The first column represents the longitude of the center of each polygon, while the
            second column represents its latitude.
    
            gdf (geopandas.geodataframe.GeoDataFrame): A geopandas dataframe containing the geospatial data 
            loaded from the geopackage file.
        """
        
        # Load data from geopackage file using geopandas
        gdf = gpd.read_file(filename)
        gdf = gdf.to_crs('3857') # Convert to latlong
        gdf = gdf.explode(index_parts=True)  # Convert multipolygon to polygon
        self.gdf = gdf
        

    def mirrorPolygons(self):
        # switches the coordinates of the polygons such that it is in latlon format
        mirroredPolygons = []
        for polygon in self.Geometry:
            # Loop through all coordinates and store their latitude and longitude in a grid
            mirroredPolygon = np.zeros((len(polygon.exterior.coords), 2), dtype=np.float32)
            for i, coord in enumerate(polygon.exterior.coords):
                loc = np.zeros(2, dtype=np.float32)
                loc[0] = coord[1]
                loc[1] = coord[0]
                mirroredPolygon[i, :] = loc
            MappedPolygon = Polygon(mirroredPolygon)
            mirroredPolygons.append(MappedPolygon)
        self.Geometry = mirroredPolygons


    def map2grid(self, latlon0: tuple) ->tf.Tensor:
        """
        Maps the coordinates in `Coordinates` to a grid that follows the reference coordinate `latlon0`.
        
        Args:
            latlon0: A tuple containing the reference coordinate in the form (latitude, longitude).
        
        Returns:
            Locations: TensorFlow Tensor of shape (n,2) containing the mapped coordinates.
        
        Notes:
            This function calculates the distance in meters of each coordinate in `Coordinates` to the reference
            coordinate `latlon0`. It then maps the coordinates to a grid based on their relative position to the reference
            coordinate, with the reference coordinate as the origin of the grid. The resulting `Locations` array is returned.
        """        
        # Loop through all coordinates and store their latitude and longitude in a grid
        Locations = np.zeros(self.Coordinates.shape, dtype=np.float32)
        for i in range(self.Coordinates.shape[0]):
            loc = np.zeros(2, dtype=np.float32)
            loc[0] = distance.distance(latlon0, [self.Coordinates[i, 0], latlon0[1]]).m
            loc[0] = loc[0] if (latlon0[0] < self.Coordinates[i, 0]) else -loc[0]
            loc[1] = distance.distance(latlon0, [latlon0[0], self.Coordinates[i, 1]]).m
            loc[1] = loc[1] if (latlon0[1] < self.Coordinates[i, 1]) else -loc[1]
            Locations[i, :] = loc        
            
        # Loop through all wijk_centers and store their latitude and longitude in a grid
        wijk_centers = np.zeros(self.wijk_centers.shape, dtype=np.float32)
        for i in range(self.wijk_centers.shape[0]):
            # for the wijk centers
            loc = np.zeros(2, dtype=np.float32)
            loc[0] = distance.distance(latlon0, [self.wijk_centers[i, 0], latlon0[1]]).m
            loc[0] = loc[0] if (latlon0[0] < self.wijk_centers[i, 0]) else -loc[0]
            loc[1] = distance.distance(latlon0, [latlon0[0], self.wijk_centers[i, 1]]).m
            loc[1] = loc[1] if (latlon0[1] < self.wijk_centers[i, 1]) else -loc[1]
            wijk_centers[i, :] = loc
            
        self.Locations = tf.Variable(Locations, trainable=False, dtype=tf.float32)
        self.wijk_centers = tf.Variable(wijk_centers, trainable=False, dtype=tf.float32)
        
        
    def polygon2grid(self, latlon0: tuple) -> list:
        """
        Maps the coordinates in `Polygons` to a grid that follows the reference coordinate `latlon0`.
        
        Args:
            latlon0: A tuple containing the reference coordinate in the form (latitude, longitude).
            #Polygons (GeoSeries): A GeoSeries object containing Polygon objects to be mapped to a grid.
        
        Returns:
            MappedPolygons: A list of `Polygon` objects containing the mapped coordinates.
        
        Notes:
            This function calculates the distance in meters of each coordinate in `Polygons` to the reference
            coordinate `latlon0`. It then maps the coordinates to a grid based on their relative position to the reference
            coordinate, with the reference coordinate as the origin of the grid. The resulting `MappedPolygons` list
            contains `Polygon` objects with the mapped coordinates.
        """
        
        MappedPolygons = []
        for polygon in self.Geometry:
            # Loop through all coordinates and store their latitude and longitude in a grid
            MappedCoordinates = np.zeros((len(polygon.exterior.coords), 2), dtype=np.float32)
            for i, coord in enumerate(polygon.exterior.coords):
                loc = np.zeros(2, dtype=np.float32)
                loc[0] = distance.distance(latlon0, [latlon0[0], coord[1]]).m
                loc[0] = loc[0] if (latlon0[0] < coord[0]) else -loc[0]
                loc[1] = distance.distance(latlon0, [coord[0], latlon0[1]]).m
                loc[1] = loc[1] if (latlon0[1] < coord[1]) else -loc[1]
                MappedCoordinates[i, :] = loc
            MappedPolygon = Polygon(MappedCoordinates)
            MappedPolygons.append(MappedPolygon)
        
        self.GeometryGrid = MappedPolygons



    def buurt_filter(self, devmode: bool = False):
        """
        Filters the socio-economic data based on whether the neighbourhoods are present in the geopandas data and 
        stores the relevant data in class variables.
        
        Args:
            devmode: boolean that allows for error messages when loading buurten. Default is False.
                    
        Notes:
            This function compares each neighbourhood in the socio-economic data to the `buurtnaam` column of the 
            geopandas dataframe stored in the `gdf` class variable. If a neighbourhood is present in the geopandas data,
            the index of the corresponding row is appended to the `index` list. The socio-economic value, number of
            Population, and name of the neighbourhood are also stored in separate lists. The lists are then converted to
            numpy arrays, and the `center_coordinates` class variable is filtered based on the `index` list. A warning
            message is printed for any neighbourhood in the socio-economic data that is not present in the geopandas data.
        
        Attributes:
            Socioeconomic_data (tf.Variable): A 1D numpy array of floats containing the socio-economic value of each 
            neighbourhood that is present in the geopandas data.
            
            Population (tf.Variable): A 1D numpy array of floats containing the number of private Population in each 
            neighbourhood that is present in the geopandas data.
            
            neighbourhoods (numpy.ndarray): A 1D numpy array of strings containing the names of the neighbourhoods that 
            are present in the geopandas data.
            
            Coordinates (tf.Variable): A 2D numpy array of shape (n, 2), where n is the number of neighbourhoods 
            present in the geopandas data. The first column represents the longitude of the center of each polygon, while 
            the second column represents its latitude.
        """
        ## Load the shapes from buurten gdf
        if devmode: print("WARNING: GDF CAN ONLY FIND BUURTEN AND NOT WIJKEN OR CITIES. THEREFORE, A LOT OF DATA WILL BE MISSING:")
        
        Geometry=[]
        indices=[]
        Coordinates=[]
        geometry_gdf = self.gdf.geometry.tolist()
        truefalse=False # used to check if the loc is found in the gdf file
        for i, code in enumerate(self.neighbourhood_codes):
            index = tf.where(self.gdf.buurtcode == code).numpy()[0][0]
            Geometry.append(geometry_gdf[index])
            #Coordinates.append(self.center_coordinates[index])
            # load the center coordinates
            meanx=np.mean(geometry_gdf[index].exterior.xy[0])
            meany=np.mean(geometry_gdf[index].exterior.xy[1])
            Coordinates.append([meanx,meany])
            
            indices.append(i)
            truefalse=True
            
            # error message
            if devmode and not truefalse:
                print("Warning:",self.neighbourhoods[i],"has not been found in gdf data. Check if instance should have been found")

        self.gather(indices)
        self.Geometry = Geometry
        self.Coordinates = tf.Variable(Coordinates, trainable=False, dtype=tf.float32)
        self.N = self.Socioeconomic_data.shape[0]
        
        
    def find_polygon_neighbours(self):
        try:
            self.GeometryGrid
        except:
            raise Exception("Polygons (GeometryGrid) have not been generated. Use self.polygon2grid().")
        
        # Loop through each polygon and find its neighbours
        neighbours = []
        extra_append = []
        for i, poly_i in enumerate(self.GeometryGrid):
            neighbours_i = []
            
            # Loop through each other polygon and check if it shares a common edge with poly_i
            for j, poly_j in enumerate(self.GeometryGrid):
                if i != j and poly_i.intersects(poly_j):
                    if poly_i.touches(poly_j) and (
                            isinstance(poly_i.boundary.intersection(poly_j.boundary), MultiLineString)
                            or isinstance(poly_i.boundary.intersection(poly_j.boundary), MultiPoint)):
                        neighbours_i.append(j)
        
            # if no neighbours are found, look for polygons that touch with points instead of edge
            if len(neighbours_i)==0:
                for j, poly_j in enumerate(self.GeometryGrid):
                    if i != j and poly_i.intersects(poly_j):
                        neighbours_i.append(j)
                        extra_append.append([j, i])
            
            
                # if no neighbours are found, find it via KNN
                #if len(neighbours_i)==0:
                # load coordinates
                xi_coords = np.array(poly_i.exterior.xy[0].tolist())
                yi_coords = np.array(poly_i.exterior.xy[1].tolist())
                minDist = []
                idx = []
                for j, poly_j in enumerate(self.GeometryGrid): # loop over the other polygons
                    if i!=j and not (j in neighbours_i):
                        # load coordinates
                        xj_coords = np.array(poly_j.exterior.xy[0].tolist()) 
                        yj_coords = np.array(poly_j.exterior.xy[1].tolist())
                        # calculate distance between i and j
                        x_dist = xi_coords[:, np.newaxis] - xj_coords
                        y_dist = yi_coords[:, np.newaxis] - yj_coords
                        # save the minimum distance from 
                        minDist.append( np.min(x_dist**2+y_dist**2) )
                        idx.append(j)
                
                for j in np.argsort(minDist)[:2]: # we take the two closest areas and add them
                    if idx[j] is not None:
                        neighbours_i.append(idx[j])
                        extra_append.append([idx[j], i])
                    else: # raise error when no indices are found, this should not be possible
                        raise Exception("No nearest neighbours found via KNN")
                        
            neighbours.append(neighbours_i)
        
        # in the list extra_append, which contains special cases of neighbours (only touches point or KNN)
        # the inverse also needs to be done, the special cases need to be added to their counterparts.
        for index in extra_append:
            neighbours[index[0]].append(index[1])
        
        return np.array(neighbours, dtype=list)
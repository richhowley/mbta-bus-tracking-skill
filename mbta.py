# Handle MBTA API calls

from mycroft.util.parse import match_one
import requests
import re


class MBTA():
  
  ################ API DISCLAIMER ################
  #
  # The Massachusetts Department of Transportation (MassDOT)
  # is the provider of MBTA Data.
  # The author is not nn agent or partner of 
  # MassDOT or its agencies and authorities
  
 
  def __init__(self, apiKey, trackCount):
    
    self.routeInfo = None;        # dictionary with info on all bus routes

    # error flag valid after API is called
    self.serverError = False
       
    # save API key
    self.apiKey = apiKey;
    
    self.currentRoute = None      # entry from routInfo for selected route
    self.currentDirections = None # direction options for current route - list of tuples
    self.currentDirection = ""    # used in queries, index into current route directions as string
    self.stopId = ""              # internal ID of selected bus stop, used to get predicitons
    self.stopName =""             # text name of bus stop
    self.busStops = dict()        # dictionary of stop names, ids in slected direction
    self.predTimes = dict()       # dictionary of trip ids, predictated arrival times
    self.maxTrackCnt = int(trackCount) # max # of buses to track
    self.lastTrack = ""           # last trip to track - stop when no longer in predictions
    self.savedrequet = ''
    
  # settings have been changed on Home
  def updateSettings(self, apiKey, trackCount):
  
    self.apiKey = apiKey
    self.maxTrackCnt = int(trackCount) # max # of buses to track
  
  
  # reset class, call when stopping tracking
  def reset(self):

    self.currentRoute = None
    self.currentDirection = ""
    self.stopId = "" 
    
  # get data from MBTA API at given endpoint with passed arguments
  def _getData(self,endPoint, args=None):

    retVal = None;
     
    # clear error flag
    self.serverError = False
     
    # base url
    api_url = "https://api-v3.mbta.com/{}".format(endPoint)

    # if we are using an api key and have args
    if self.apiKey != None and args != None:
      
      # url?key%args
       api_url = "{}?api_key={}&{}".format(api_url,self.apiKey,args)
       
    elif self.apiKey != None:
      
      # url?key
      api_url = "{}?api_key={}".format(api_url,self.apiKey)
       
    elif args != None :
      
      # url?args
      api_url = "{}?{}".format(api_url,args)
      
    try:
 
      # get requested data
      r = requests.get(api_url)
      
      # check if we got any data before setting return value
      retVal = r.json()['data'] if len(r.json()['data']) > 0 else None
      
    except:

      # set error flag
      self.serverError = True
    
    return retVal


  # API calls die silently, return true if last call
  # resulted in an error
  def callError(self):
    return self.serverError

    
  # information on all MBTA bus routes is read from server
  # not all information is relevant to skill, we build a
  # dictionary with the info we need
  # this API call is necessary before getting any predictions
  # and will only be done once
  def readRoutes(self):
    
    # if route info has not been read yet
    if( self.routeInfo == None ):
      
      # create empty dicitonary
      self.routeInfo = dict()
      
      # get info on all bus routes - only called once
      routes = self._getData('routes',"filter[type]=3&sort=sort_order")

      if routes != None:
        
        # build dictionary with the info we need on each route
        # key is short name
        for rt in routes:
          self.routeInfo[rt['attributes']['short_name']] = {
                                         'id': rt['id'],                               # id
                                         'short_name' : rt['attributes']['short_name'],# short name
                                         'long_name' : rt['attributes']['long_name'],  # long name
                                         'dirs' : rt['attributes']['direction_names'], # directions
                                         'dest' : rt['attributes']['direction_destinations'] # terminus
                                      }
            
            
  # set current route based on passed name
  # return route name or None
  def setRoute(self, routeName):
    
    self.currentRoute = None;
    
    # make certain routes are loaded
    self.readRoutes()
    
    # look in the dictionary
    rt = self.routeInfo.get(routeName)

    # if we got a valid route
    if rt != None:
      self.currentRoute = self.routeInfo[routeName]
      
    return(None if not rt else self.currentRoute['short_name'])
  
  # return object that can be saved to settings
  # to remember current route and direction
  def getRouteSettings(self):
    
    # current route basic info
    currRoute = self.currentRoute
    
    # add current direction and stop id
    currRoute["direction"] = self.currentDirection
    currRoute["stopid"] = self.stopId
    currRoute["stopName"] = self.stopName
    return(currRoute)
  
  # restore a root saved in settings
  # return route name
  def restoreRoute(self, rt):

    # current direction, stop id and stop name are not in route dict
    self.currentDirection = rt.pop('direction', None)
    self.stopId = rt.pop('stopid', None);
    self.stopName = rt.pop('stopName')
    
    # now route is reduced to proper contents of current route
    self.currentRoute = rt
 
    
    # fill current directions array
    self.getDirections()
    
    return self.currentRoute['short_name'];

  # getters for info on restored route
  def getStopName(self):
    return self.stopName
   
  def getDirDest(self):
    return(self.currentDirections[self.currentDirection])    

  
  # return list of directions and destinations
  # each element in list is direction, destination tuple
  #   directions are usually Inbound and Outbound
  def getDirections(self):
    
    self.currentDirections = []
    
    # append tuple for each direction 
    for idx, d in enumerate(self.currentRoute["dirs"]):
      self.currentDirections.append((self.currentRoute["dirs"][idx],self.currentRoute["dest"][idx]))
      
    return(self.currentDirections)
  
  # pass string for direction - could be inbound, outboud or terminus
  # a tuple of (direction name, destination name) for best match is returned
  def setDirection(self, str):

    # build list of directions and destinations as strings
    dirList = [' '.join(x) for x in self.currentDirections]

    # select one destinaiton
    dirKey, dirConfidence = match_one(str, dirList)

    # set direction id to index of selected destination
    self.currentDirection = dirList.index(dirKey)
    
    return(self.currentDirections[self.currentDirection])

  # format stop name to (hopefully) match spoken version
  def formatStopName(self, str):
    
    # Street for St
    str = re.sub(r'St ', 'Street ', str)    
    str = re.sub(r' St$', ' Street ', str)
    
    # opposite for opp
    str = re.sub(r'opp ', 'opposite ', str)

    return(str)

  # build dictionary of bus stops for current route in selected direction
  # key is name, to compare with utterance
  # value is id, to use for API calls
  def getStops(self):
    
    # ask API for stops
    routeStops = self._getData('stops',
                                "filter[direction_id]={}&filter[route]={}"
                                .format(self.currentDirection, self.currentRoute["id"]))

      
    # empty dictionary
    self.busStops = dict()
    
    # create entry in dictionary for each bus stop
    for stop in routeStops:
      stopKey = self.formatStopName(stop['attributes']['name'])
      stopKey = stopKey.lower()
      self.busStops[stopKey] = stop['id']
 

  # a bus stop name is passed, match to stop on route and set stop id
  #  return name found
  def setStop(self, stopName):
  
    # build dictionay of stops if necessary
    self.getStops()

    # find closest match on route
    theStop = key, confidence = match_one(stopName, list(self.busStops))
    self.stopId = self.busStops.get(key);    
    
    # record stop name
    self.stopName = theStop[0]
      
    return(self.stopName)
  
  # get arrival predictions for current route in the selected direcation at the chosen stop
  # return (possibly empty) list of arrival time, trip id tuples
  def getPredictions(self):
    
    predList = []
   
    # ask API for predictions
    predictions = self._getData('predictions',
                                "filter[direction_id]={}&filter[route]={}&filter[stop]={}"
                                .format(self.currentDirection,self.currentRoute["id"],self.stopId))

    # if we got valid predictions
    if predictions != None:

          # build list of arrival time, trip id tuples
          predList = list(map(lambda x: (x['attributes']['arrival_time'],
                                         x['relationships']['trip']['data']['id']), predictions))
          
          # remove tuples where arrival time is none
          predList = [p for p in predList if p[0] != None ]

    return(predList)
  
  # return arrival predictions as list
  #  predictions are datatime objects with time zone
  def getArrivals(self):
    
    # get predictions
    self.predTimes = self.getPredictions()
      
    # only return prediction times
    return(None if len(self.predTimes) == 0 else [x[0] for x in self.predTimes])
 
  # begin tracking buses, return list of arrival predictions
  def startTracking(self):
    
    # get predictions
    self.predTimes = self.getPredictions()
    
    # if we got any predictions
    if len(self.predTimes) > 0:
      
      # record last trip we will track 
      self.lastTrack = self.predTimes[min(len(self.predTimes),self.maxTrackCnt)-1][1]

      
    # only return prediction times
    #  predictions are datatime objects with time zone
    return(None if len(self.predTimes) == 0 else [x[0] for x in self.predTimes][:self.maxTrackCnt])
 
  # call periodically for current predictions of bus being tracked
  # startTracking must be called first to record the last trip tracked
  # return list of arrival predictions
  def updateTracking(self):
    
    idx = -1  # assume we won't find the last tracked bus
    
    # get predictions
    self.predTimes = self.getPredictions()
      
    if self.predTimes != None:
      
      # get index of last tracked bus
      try:
        # build list with trip id of last tracked bus then find its index in prediction list
        idx = self.predTimes.index([x for x in self.predTimes if x[1] == self.lastTrack][0])
      except:
       self.reset()
            
 
    # return prediction times up to last tracked bus
    # if we got valid predictions and last
    # tracked trip is still in list
    return(None if idx < 0
           else [x[0] for x  in self.predTimes][:idx+1])
  
    # call when done tracking or stopped by voice command
  def stopTracking(self):
    self.reset()

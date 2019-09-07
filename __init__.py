from adapt.intent import IntentBuilder
from mycroft import MycroftSkill, intent_file_handler
from mycroft.util.parse import match_one
from mycroft.util.parse import fuzzy_match
from mycroft.util.log import getLogger
import mycroft.util
from mycroft.audio import wait_while_speaking
from mycroft import intent_handler
import requests
import datetime
from pytz import timezone
import pickle
import re
import copy


LOGGER = getLogger(__name__)

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
    self.maxTrackCnt = int(trackCount) # max # of busses to track
    self.lastTrack = ""           # last trip to track - stop when no longer in predictions
 
    # format API URLs
    ROUTE_URL = "https://api-v3.mbta.com/routes?filter[type]=3&sort=sort_order&api_keyapi_key={}".format(apiKey)
    STOP_URL = "https://api-v3.mbta.com/stops?api_key={}".format(apiKey)
    PRED_URL = "https://api-v3.mbta.com//predictions?sort=arrival_time,direction_id&api_keyapi_key={}".format(apiKey)

 
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
     
    # format URL with end point and API key
    api_url = "https://api-v3.mbta.com/{}?api_key={}".format(endPoint,self.apiKey)
    
    # add arguments if necessary
    if( args != None ):
      api_url = "{}&{}".format(api_url,args)

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
                                .format(self.currentDirection,self.currentRoute["id"]))

      
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
 
  # begin tracking busses, return list of arrival predictions
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
    
TZ_STR_IDX = len('-05:00') * (-1) # time zone string, used to strip tz from api dates
ROUTE_FILE = 'savedroutes'  # file for saving route information

class MbtaBusTracking(MycroftSkill):
  
    def __init__(self):
        MycroftSkill.__init__(self)
        super(MbtaBusTracking, self).__init__(name="MbtaBusTracking")
       
        # create MBTA object to handle api calls     
        self.t = MBTA(self.settings.get('api_key'),self.settings.get('maxTrack', 3))          
             
        self.routeName = None           # bus route
        self.requestTracking = False    # True => last request was for tracking, not arrivals
        self.directions = None          # direction name, terminus tuple for route
        self.stopName = None            # bus stop 
        self.dirName = None             # direction of travel
        self.destName = None            # terminus for direction
        self.savedRoutes = dict()       # routes save to disk
        self.trackingInterval = max(30, (self.settings.get('trackingUpateFreq', 30))) # enforce min tracking updates
                    
        # watch for changes on HOME
        self.settings.set_changed_callback(self.on_websettings_changed)
        
      # try to read saved routes
        try:
            with self.file_system.open(ROUTE_FILE , 'rb') as f:
                self.savedRoutes =  pickle.load(f)
        except:
            pass
        

    def initialize(self):
    
        # make a vocabulary from saved routes
        if self.savedRoutes:
          for s in self.savedRoutes:
              self.register_vocabulary(s, 'SavedRouteNames')
 
    # handle change of setting on home
    def on_websettings_changed(self):
      
      # try to read api key
      self.apiKey = self.settings.get('api_key')
      
      LOGGER.info('MBTA skill api set to ' + self.apiKey)
      
      # create MBTA object with new settings
      self.t = MBTA(self.settings.get('api_key'),self.settings.get('maxTrack', 3))          
 
      self.trackingInterval = max(30, (self.settings.get('trackingUpateFreq', 30))) # enforce min tracking updates

           
    # speak list of passed arrival times
    def announceArrivals(self,eta):
      
      # get current datetime for east coast without timecode
      currentTime = datetime.datetime.now((timezone('America/New_York'))).replace(tzinfo=None)
      
      # build datetime objets from strings in predection list
      # strip timezone first since we cannot count on fromisoformat() being available (3.7+)
      eta = [datetime.datetime.strptime(x[0:TZ_STR_IDX], '%Y-%m-%dT%H:%M:%S') for x in eta]
            
      # calculate waiting times
      wt = [x-currentTime for x in eta if x > currentTime]
      
      arrivalCount = len(wt)
      
      # speak prefix if necessary
      if arrivalCount > 0:
        
        # add stop to prefix string
        prefix = {'stop': self.stopName}
        
        # might be updating arrivals while Mycroft is speaking, so wait
        wait_while_speaking()

        self.speak_dialog("Bus.Arrival.Prefix", prefix)
      
        for waitTime in wt:
           
          # wait for previous arrival announcement to finish
          wait_while_speaking()
      
          # calculate hour and minutes from datetime timedelta seconds
          arrival = {
             'hour': waitTime.seconds // 3600,
             'minutes' : (waitTime.seconds % 3600) // 60
          }
                    
          #  one hour or longer
          if (arrival['hour'] > 0):
 
            # round down to one hour if only one minute over
            if(arrival['minutes'] < 2 ):

              self.speak_dialog("Arriving.Hour", arrival )
            
            else:
            
              # arrives in 1 hour and some minutes

              self.speak_dialog("Arriving.Hour.Minutes", arrival )
            
          elif arrival['minutes'] > 1:
            
            # arrives in more than one minute

            self.speak_dialog("Arriving.Minutes", arrival )
   
          elif arrival['minutes'] == 1:
            
            # arrives in one minute

            self.speak_dialog("Arriving.Minute", arrival )
            
          else:
            
            # arrives in less than a minute
            self.speak_dialog("Arriving.Now")
        
        
        return arrivalCount
    
    # call to stop tracking
    def endTracking(self):
      
        # stop updates
        self.cancel_scheduled_event('BusTracker')
        
        # tell T object that we are no longer tracking
        self.t.stopTracking()
        
    # calllback for tracking updates
    def updateTracking(self):
      
      # get predictions     
      eta = self.t.updateTracking()
      
      # if any arrivals predicted for our stop
      if eta != None:
        
        # speak times
        self.announceArrivals(eta)
        
      else:
        
        # last tracked bus has passed the stop, end updates
        self.endTracking()

        
    # call to start tracking arrivals
    # afer route, direction and stop have been set
    def startTracking(self):
   
        # get predictions
        eta = self.t.startTracking()
        
        # if any arrivals predicted for our stop
        if eta != None:
          
          # speak times
          self.announceArrivals(eta)
          
          # schedule updates 
          self.schedule_repeating_event(self.updateTracking,
                                        None,
                                        self.trackingInterval,
                                        name='BusTracker')
        else:
          
          # no busses running
          stopInfo = {'name' : self.stopName}
          self.speak_dialog("No.Busses.Found",stopInfo)
       
    # call when an arrival route, direction and
    # stop have been set
    def getArrivals(self):
      
      # ask API for arrival times
      eta = self.t.getArrivals()
      
      # begin arrival announcments
      announcement = {
                        'route': self.routeName,
                        'dest': self.destName
                      }
      self.speak_dialog("Service.Announcement",announcement)
      
      # speak arrival times if we got any
      if eta != None:
        self.announceArrivals(eta)
      else:
        stopInfo = {'name' : self.stopName}
        self.speak_dialog("No.Busses.Found",stopInfo)


    # write route to file
    def writeRoutes(self):
        
        # open file in /home/pi/.mycroft/skills
        with self.file_system.open(ROUTE_FILE , 'wb') as f:

          # serialize dictionary
          pickle.dump(self.savedRoutes, f, pickle.HIGHEST_PROTOCOL)
          

    # save the current route as a shortcut
    def saveRoute(self, name):
    
        # add current route to saved routes dictionary
        self.savedRoutes[name] = self.t.getRouteSettings()

        # wrtie it to disk
        self.writeRoutes()
        
        # add to vocabulary
        self.register_vocabulary(name, 'SavedRouteNames')
 
        
    # remove saved route from file
    def removeRoute(self, name):
      
      # if route is in dict, remove and save
      if self.savedRoutes.pop(name, None) != None:
        self.writeRoutes()
        
    # try to restore route with passed name, return True if successful
    def restoreRoute(self, name):
      
      retVal = False
      
      
      # look up route associated with this name
      restoredRoute = self.savedRoutes.get(name)

      # if we got one
      if restoredRoute != None:
        
        # set up API class with copy of route object
        self.routeName = self.t.restoreRoute(copy.deepcopy(restoredRoute))
         
        # set class variables 
        self.stopName = self.t.getStopName()
        self.dirName, self.destName = self.t.getDirDest()
        
        retVal = True
            
      return retVal

    # set proper route name based on utterance
    # and get directions for route
    def setRouteAndDirection(self, routeName):
      
        # Silver Line and Crosstown must be abreviated for API calls
        routeName = routeName.replace('crosstown ','CT')
        routeName = routeName.replace('silverline ','SL')
        
        # quirks fround in testing
        routeName = routeName.replace('to', '2')
        routeName = routeName.replace('for', '4')


        # tell API which route we are riding
        self.routeName = self.t.setRoute(routeName)

        # read directions for this route
        if self.routeName:
          self.directions = self.t.getDirections()
          
        return self.routeName

    # prompt for direction and set context
    def setDirectionContext(self):

      # possible directions have already been set
      dirChoices = {
        
          'dir1': self.directions[0][0],
          'dest1': self.directions[0][1],
          'dir2': self.directions[1][0],
          'dest2': self.directions[1][1]        
      }
      
      # prompt and set context
      self.speak_dialog('Which.Direction',dirChoices,expect_response=True)
      self.set_context('DirectionNeededContex')

    # prompt for direction and set context
    def setStopContext(self):

      self.speak_dialog('Which.Stop', expect_response=True)
      self.set_context('StopNeededContext')

    # remove all contexts we may have set
    def removeContexts(self):

      self.remove_context('RouteNeededContex')
      self.remove_context('DirectionNeededContex')
      self.remove_context('StopNeededContex')

    # process request for arrivals or tracking
    def processRequest(self, message, tracking):

      # may have set context in previous call
      self.removeContexts()

      # may already be tracking
      self.endTracking()
        
      # init class variables
      self.routeName = None
      self.dirName = None
      self.destName = None
      self.stopName = None
      self.requestTracking = tracking     
      
      # get fields from utterance 
      routeName = message.data.get("Route.Name", None)
      direction = message.data.get("Direction", None)
      stop = message.data.get("Stop", None)
  
      
      # set up for API call
      if routeName:
        
        # set route name
        routeName = self.setRouteAndDirection(routeName)
        
        # check for error
        if self.t.callError() is True:
          
          # server error
          self.speak_dialog("Error.calling.server")
                    
          # clear route name
          routeName = None;
        

      # only accept direction if we have a route
      if routeName and direction:
        
        # set direction from utterance
        self.dirName, self.destName = self.t.setDirection(direction)
        #print('Direction set to {}'.format(self.dirName))
       
      # only accept stop name if we have route and direction
      if routeName and direction and stop:
        
        self.stopName = self.t.setStop(stop)
        #print('Direction set to {} toward {} at {}'.format(self.dirName,self.destName,self.stopName))
 
     
      # if we got all the info needed,get arrivals
      if( self.routeName and self.dirName and self.stopName ):
      
        # good to go - list arrivals or start tracking
        if self.requestTracking:
          self.startTracking()
        else:
          self.getArrivals()
      
      elif( self.routeName and self.dirName):
        
        # got route and direction, need stop
        self.setStopContext()
        #print('got route {} and direction {}'.format(self.routeName, self.dirName))
      
      elif self.routeName:
        
         # got route,need direction
         #print('got route {} '.format(self.routeName))
         
         # now we nedd a direction
         self.setDirectionContext()
          
      else:
            
          # if we are here it is because no route was in the
          # utterance, the route in the utterance was not valid
          # or there was an error calling the API
          #
          # set context to get a valid route as long as there was
          # not an error calling the API
          #
          if self.t.callError() is False: 
            
            # need route name
            self.speak_dialog('Which.Route',expect_response=True)
            self.set_context('RouteNeededContex')

    # set route based on context
    @intent_handler(IntentBuilder('')
        .require('RouteNeededContex')
        .optionally('Route').require('Route.Name').build())
    def handle_route_context_intent(self, message):

      # done with this context
      self.remove_context('RouteNeededContex')

      # pull route from message
      routeName =  message.data.get("Route.Name", None)
      
      # set route name and direction
      routeName = self.setRouteAndDirection(routeName)

      # check for server error
      if self.t.callError() is True:
        
        # server error
        self.speak_dialog("Error.calling.server")
             
      else:

        # now we nedd a direction
       self.setDirectionContext()
      
    # set direction based on context
    @intent_handler(IntentBuilder('')
        .require('DirectionNeededContex').build())
    def handle_direction_context_intent(self, message):
      
      # done with this context
      self.remove_context('DirectionNeededContex')
      
      # set direction from utterance
      self.dirName, self.destName = self.t.setDirection(message.data.get('utterance'))
      #print('Direction set to {}'.format(self.dirName))
      
      # now we need a stop
      self.setStopContext()

    # set stop based on context
    @intent_handler(IntentBuilder('')
        .require('StopNeededContext').build())
    def handle_stop_context_intent(self, message):
      
      # done with this context
      self.remove_context('StopNeededContext')
      
      # set stop from utterance
      self.stopName = self.t.setStop(message.data.get('utterance'))

      # good to go - list arrivals or start tracking
      if self.requestTracking:
       self.startTracking()
      else:
       self.getArrivals()
          
    # arrivals for bus route
    @intent_handler(IntentBuilder('')
        .require('T.Bus')
        .require('Arrivals')
        .optionally('Route')
        .optionally('Route.Name')
        .optionally('Direction')
        .optionally('Stop')
        .build())
    def handle_arrivals_intent(self, message):
       # process arrivals request
      self.processRequest(message, False)

    # tracking bus route
    @intent_handler(IntentBuilder('')
        .require('T.Bus')
        .require('Tracking')
        .optionally('Route')
        .optionally('Route.Name')
        .optionally('Direction')
        .optionally('Stop').build())
    def handle_tracking_intent(self, message):
      
      # process tracking request
      self.processRequest(message, True)

    # save shortcut
    @intent_handler(IntentBuilder('')
        .require('Save').require('T.Bus').require('Shortcut').build())
    def handle_save_route_intent(self, message):

      
      # need full route information to save
      if( self.routeName and self.dirName and self.stopName ):
        
        # get name for shortcut
        shortcutName = self.get_response("Shortcut.Prompt");
        
        if shortcutName:
          
          # save route under passed name
          self.saveRoute(shortcutName)
          
          shortcutInfo = {'shortcut': shortcutName}
          self.speak_dialog("Save.Complete", shortcutInfo)
        
      else:
        
        # don't have complete info
        self.speak_dialog("Not.Enough.Info")


    # remove shortcut
    @intent_handler(IntentBuilder('')
        .require('Remove').require('T.Bus').optionally('Shortcut').require('SavedRouteNames').build())
    def handle_remove_route_intent(self, message):
    
      # extract short cut
      shortcutNmae = message.data.get("SavedRouteNames", None)
              
      # remove it
      self.removeRoute(shortcutNmae)
        
      shortcutInfo = {'shortcut': shortcutNmae}
      self.speak_dialog("Delete.Complete", shortcutInfo)

    # list shortcuts
    @intent_handler(IntentBuilder('')
        .require('List').require('T.Bus').require('Shortcuts').build())
    def handle_list_saved_route_intent(self, message):
      # build list of rotue names
      routeList = [s for s in self.savedRoutes]
 
      if len(routeList) > 0:
        
        # speak the names
        routes = {'routes': ' '.join(routeList)}
        self.speak_dialog('List.Saved', routes)
        
      else:
        
        self.speak_dialog('No.Saved.Routes')

    # tracking for a saved route
    @intent_handler(IntentBuilder('')
        .require('T.Bus').require('Tracking').optionally('Route').require('SavedRouteNames').build())
    def handle_saved_tracking_intent(self, message):

      # may already be tracking
      self.endTracking()
      
      # restore named route and start tracking
      routeName = message.data.get("SavedRouteNames", None)
      self.restoreRoute(routeName)
      self.startTracking()
                 
    # arrivals for a saved route              
    @intent_handler(IntentBuilder('')
        .require('T.Bus').require('Arrivals').optionally('Route').require('SavedRouteNames').build())
    def handle_saved_arrivals_intent(self, message):

      # pull shortcut name from intent
      shortCut = message.data.get("SavedRouteNames", None)
      # if shortcut has been deleted it will still be
      # in vocablulary until restart

      if self.savedRoutes.get(shortCut, None):
        
        # may already be tracking
        self.endTracking()
      
         # restore route and list arrivals
        self.restoreRoute(shortCut)
        self.getArrivals()
  
    # stop tracking
    @intent_handler(IntentBuilder('')
        .require('T.Bus').require('Shutdown').build())
    def handle_shutdown_intent(self, message):
      
      # stop tracking
      self.endTracking()
      
      # reset contexts
      self.removeContexts()
      
      self.speak_dialog('Shutdown.Message')
                                          


def create_skill(): 
    
    return MbtaBusTracking()


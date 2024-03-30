#
#   Mycroft sill to announce predicted arrival times
#   of MBTA buse. It can also be used to track buses,
#   continually anouncing arrival times.
#

from adapt.intent import IntentBuilder
from mycroft import MycroftSkill, intent_file_handler
from mycroft.util.parse import match_one
#from mycroft.util.parse import fuzzy_match
import mycroft.util
from mycroft.audio import wait_while_speaking
from mycroft import intent_handler
# import requests
import datetime
from pytz import timezone
import pickle
import re
import copy
from . mbta import MBTA

TZ_STR_IDX = len('-05:00') * (-1) # time zone string, used to strip tz from api dates
ROUTE_FILE = 'savedroutes'  # file for saving route information

class MbtaBusTracking(MycroftSkill):

    def __init__(self):
        MycroftSkill.__init__(self)
        super(MbtaBusTracking, self).__init__(name="MbtaBusTracking")

    def initialize(self):

        self.apiKey = None # API can be used without key

        # using api key?
        self.useownkey = self.settings.get('useownkey')

        #   yes, read it from settings
        if self.useownkey:
          self.apiKey = self.settings.get('api_key')

        # create MBTA object to handle api calls
        self.t = MBTA(self.apiKey,self.settings.get('maxTrack', 3))

        self.routeName = None           # bus route
        self.requestTracking = False    # True => last request was for tracking, not arrivals
        self.directions = None          # direction name, terminus tuple for route
        self.stopName = None            # bus stop
        self.dirName = None             # direction of travel
        self.destName = None            # terminus for direction
        self.savedRoutes = dict()       # routes saved to disk
        self.trackingInterval = max(30, (self.settings.get('trackingUpateFreq', 30))) # enforce min tracking updates

        # watch for changes on HOME
        self.settings_change_callback = self.on_websettings_changed

      # try to read saved routes
        try:
            with self.file_system.open(ROUTE_FILE , 'rb') as f:
                self.savedRoutes =  pickle.load(f)

            # make a vocabulary from saved routes
            if self.savedRoutes:
              for s in self.savedRoutes:
                  self.register_vocabulary(s, 'SavedRouteNames')

        except:
            pass


    # handle change of setting on home
    def on_websettings_changed(self):

      # using api key?
      self.useownkey = self.settings.get('useownkey')

      #   yes, read it from settings
      if self.useownkey:
        self.apiKey = self.settings.get('api_key')
        self.log.info('MBTA skill API key set to ' + self.apiKey)
      else:
        self.apiKey = None
        self.log.info('MBTA skill not use an API key')

      # update MBTA object with new settings
      self.t.updateSettings(self.apiKey,self.settings.get('maxTrack', 3))

      # get tracking interval
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
    # after route, direction and stop have been set
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

          # no buses running
          stopInfo = {'name' : self.stopName}
          self.speak_dialog("No.buses.Found",stopInfo)

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
        self.speak_dialog("No.buses.Found",stopInfo)


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

        # write it to disk
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

        # convert any alpha characters to uppercase
        routeName = routeName.upper()

        # tell API which route we are riding
        self.routeName = self.t.setRoute(routeName)

        # read directions for this route
        if self.routeName:
          self.directions = self.t.getDirections()

        return self.routeName

    # prompt for direction
    def setDirection(self):

      # possible directions have already been set
      dirChoices = {

          'dir1': self.directions[0][0],
          'dest1': self.directions[0][1],
          'dir2': self.directions[1][0],
          'dest2': self.directions[1][1]
      }

      # prompt for direction
      directionUtterance = self.get_response('Which.Direction',dirChoices)
      print("******** Direction Utterance *****************")
      print(directionUtterance)
      # if we got a direction, carry on
      if directionUtterance != None:
          self.handle_direction_intent(directionUtterance)

    # prompt for stop
    def setStop(self):

      stopUtterance = self.get_response('Which.Stop')

      # if we got a stop name, handle the utterance
      if stopUtterance != None:
          self.handle_stop_intent(stopUtterance)

    # remove all contexts we may have set
    def removeContexts(self):

      self.remove_context('RouteNeededContex')

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
          self.speak_dialog("Error.Calling.Server")


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
        self.setStop()
        #print('got route {} and direction {}'.format(self.routeName, self.dirName))

      elif self.routeName:

         # got route, now we need a direction
         self.setDirection()

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
        self.speak_dialog("Error.Calling.Server")

      else:

        # now we need a direction
       self.setDirection()

    # set direction based
    def handle_direction_intent(self, message):
      print("<<<<<< in handle direction >>>>>>>>") #debug
      # set direction from utterance
      self.dirName, self.destName = self.t.setDirection(message)

      # now we need a stop
      self.setStop()

    # set stop
    def handle_stop_intent(self, message):

      # set stop from utterance
      self.stopName = self.t.setStop(message)

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

Feature: bus-arrival
  Scenario: bus arrival
    Given an English speaking user
     When the user says "t bus arrivals"
     Then "mbta-bus-tracking.richhowley" should reply with dialog from "Which.Route.dialog"
	 When the user says "1"
     Then "mbta-bus-tracking.richhowley" should reply with dialog from "Which.Direction.dialog"
	 # --- test only works to this point
	 # --- maybe becuase direction dialog is so long?
	 #When the user says "outbound"
	 #Then "mbta-bus-tracking.richhowley" should reply with dialog from "Which.Stop.dialog"
	 #When the user says "Mass Ave and Beacon Street"
	 #Then "mbta-bus-tracking.richhowley" should reply with dialog from "Bus.Arrival.Prefix.dialog"

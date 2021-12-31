Feature: bus-arrival
  Scenario: bus arrival
    Given an English speaking user
     When the user says "t bus arrivals"
     Then "mbta-bus-tracking.richhowley" should reply with dialog from "Which.Route.dialog"
     And the user replies "1"
     Then "mbta-bus-tracking.richhowley" should reply with dialog from "Which.Direction.dialog"
     And the user replies "outbound"
     Then "mbta-bus-tracking.richhowley" should reply with dialog from "Which.Stop.dialog"
     And the user replies "Mass Ave and Beacon Street"
     Then "mbta-bus-tracking.richhowley" should reply with dialog from "Bus.Arrival.Prefix.dialog"

from mycroft import MycroftSkill, intent_file_handler


class MbtaBusTracking(MycroftSkill):
    def __init__(self):
        MycroftSkill.__init__(self)

    @intent_file_handler('tracking.bus.mbta.intent')
    def handle_tracking_bus_mbta(self, message):
        self.speak_dialog('tracking.bus.mbta')


def create_skill():
    return MbtaBusTracking()


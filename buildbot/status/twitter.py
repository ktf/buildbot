#
# Derived from code from the status/mail.py in buildbot 0.7.9
# Needs python-twitter installed to function.

import twitter

from zope.interface import implements
from twisted.internet import defer, threads
from twisted.mail.smtp import sendmail
from twisted.python import log as twlog

from buildbot import interfaces, util
from buildbot.status import base
from buildbot.status.builder import FAILURE, SUCCESS, WARNINGS

class TwitterNotifier(base.StatusReceiverMultiService):

    compare_attrs = ["twitname", "twitpass", "mode", "categories", "builders",
                     "message"]

    def __init__(self, twitname, twitpass, mode="all", categories=None, builders=None,
                 message="%(buildSlave)s reported build %(buildNumber)s as a %(result)s %(buildUrl)s"):
        """
        @type  twitname
        @param twitname: The twitter user
        @type  twitpass
        @param twitpass: The twitter user's password. 
        @type  mode: string (defaults to all)
        @param mode: one of:
                     - 'all': send mail about all builds, passing and failing
                     - 'failing': only send mail about builds which fail
                     - 'passing': only send mail about builds which succeed
                     - 'problem': only send mail about a build which failed
                     when the previous build passed

        @type  message: string
        @param message: a string to be used as the subject line of the message.
                       - %(buildSlave)s will be replaced with the name of the slave doing the building.
                       - %(projectName)s with the name of the project
                       - %(result)s will be the result of the build
                       - %(buildUrl)s will be the url with the details of the build.
                       - %(revision)s The revision of the change.

        @type  categories: list of strings
        @param categories: a list of category names to serve status
                           information for. Defaults to None (all
                           categories). Use either builders or categories,
                           but not both.
                        builder which provoked the message.

        @type  builders: list of strings
        @param builders: a list of builder names for which mail should be
                         sent. Defaults to None (send mail for all builds).
                         Use either builders or categories, but not both.
        """

        base.StatusReceiverMultiService.__init__(self)
        self.twitname = twitname
        self.twitpass = twitpass
        assert mode in ('all', 'failing', 'problem')
        self.mode = mode
        self.message = message
        self.categories = categories
        self.builders = builders
        self.watched = []
        self.status = None

        # you should either limit on builders or categories, not both
        if self.builders != None and self.categories != None:
            twlog.err("Please specify only builders to ignore or categories to include")
            raise # FIXME: the asserts above do not raise some Exception either

    def setServiceParent(self, parent):
        """
        @type  parent: L{buildbot.master.BuildMaster}
        """
        base.StatusReceiverMultiService.setServiceParent(self, parent)
        self.setup()

    def setup(self):
        self.status = self.parent.getStatus()
        self.status.subscribe(self)

    def disownServiceParent(self):
        self.status.unsubscribe(self)
        for w in self.watched:
            w.unsubscribe(self)
        return base.StatusReceiverMultiService.disownServiceParent(self)

    def builderAdded(self, name, builder):
        # only subscribe to builders we are interested in
        if self.categories != None and builder.category not in self.categories:
            return None

        self.watched.append(builder)
        return self # subscribe to this builder

    def builderRemoved(self, name):
        pass

    def builderChangedState(self, name, state):
        pass
    def buildStarted(self, name, build):
        pass
    def buildFinished(self, name, build, results):
        # here is where we actually do something.
        builder = build.getBuilder()
        if self.builders is not None and name not in self.builders:
            return # ignore this build
        if self.categories is not None and \
               builder.category not in self.categories:
            return # ignore this build

        if self.mode == "failing" and results != FAILURE:
            return
        if self.mode == "passing" and results != SUCCESS:
            return
        if self.mode == "problem":
            if results != FAILURE:
                return
            prev = build.getPreviousBuild()
            if prev and prev.getResults() == FAILURE:
                return
        # for testing purposes, buildMessage returns a Deferred that fires
        # when the mail has been sent. To help unit tests, we return that
        # Deferred here even though the normal IStatusReceiver.buildFinished
        # signature doesn't do anything with it. If that changes (if
        # .buildFinished's return value becomes significant), we need to
        # rearrange this.
        return self.buildMessage(name, build, results)

    def buildMessage(self, name, build, results):
        projectName = self.status.getProjectName()
        buildSlave = build.getSlavename()
        buildUrl = self.status.getURLForThing(build)
        buildNumber  = build.getNumber()

        ss = build.getSourceStamp()
        if ss is None:
            revision = "unavailable"
        else:
            revision = ""
            if ss.revision:
                source += ss.revision
            else:
                revision += "HEAD"

        if results == SUCCESS:
            result = "success"
        elif results == WARNINGS:
            result = "warnings"
        else:
            res = "failure"

        text = self.message % {
            'projectName': projectName,
            'buildSlave':  buildSlave,
            'result': result,
            'revision': revision,
            'buildUrl': buildUrl,
            'buildNumber' : buildNumber,
        }
        
        d = threads.deferToThread(_sendTwitter, self.twitname, self.twitpass, 
                                  text)
        return d

def _sendTwitter(twitname, twitpass, text):
    api = twitter.Api(twitname, twitpass)
    api.PostUpdate(text)
        

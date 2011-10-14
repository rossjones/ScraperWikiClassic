import os
import re
import datetime
import time
import uuid
import json

from twisted.internet import protocol, reactor
from twisted.web.client import Agent, ResponseDone
from twisted.internet.defer import succeed, Deferred
from twisted.internet.defer import Deferred
from twisted.internet.error import ProcessDone

from twisterconfig import logger
from twisterconfig import nodecontrollername, nodecontrollerhost, nodecontrollerport
from twisterconfig import jstime
from twisterscheduledruns import ScheduledRunMessageLoopHandler


class spawnRunner(protocol.ProcessProtocol):
    def __init__(self, client, code):
        self.client = client
        self.code = code
        self.lbuffer = [ ]
        self.httpheaders = [ ]
        self.httpheadersdone = False
        self.controllerconnection = None
        self.runobjectmaker = None
        
    def connectionMade(self):
        logger.debug("Starting run ")
    
    # called when the connection to the controntroller is opened
    def gotcontrollerconnectionprotocol(self, controllerconnection):
        controllerconnection.srunner = self
        self.controllerconnection = controllerconnection

            # generate the header element that is normally generated by dispatcher, 
            # which should in future be made by the node-controller
        msg = { 'message_type':'executionstatus', 'content':'startingrun', 'runID':self.jdata["runid"], 'uml':"directcontroller %s"%nodecontrollername, 
                'rev':self.jdata["rev"], 'chatname':self.client.chatname, 'nowtime':jstime(datetime.datetime.now())}
        self.client.writeall(json.dumps(msg))
        
            # send the data into the controller including all the code it should run
        sdata = json.dumps(self.jdata)
        logger.debug("sending: %s" % str([sdata[:1000]]))
        controllerconnection.transport.write('POST /Execute HTTP/1.0\r\n')
        controllerconnection.transport.write('Content-Length: %s\r\n' % len(sdata))
        controllerconnection.transport.write('Content-Type: text/json\r\n')
        controllerconnection.transport.write('Connection: close\r\n')
        controllerconnection.transport.write("\r\n")
        controllerconnection.transport.write(sdata)

    # messages from the UML
    def outReceived(self, data):
        logger.debug("spawnrunner received for client# %d %s" % (self.client.clientnumber, data[:180]))
            # although the client can parse the records itself, it is necessary to split them up here correctly so that this code can insert its own records into the stream.

        lines = [ ]
        spldata = data.split("\n")
        self.lbuffer.append(spldata.pop(0))
        while spldata:
            lines.append("".join(self.lbuffer))
            self.lbuffer = [ spldata.pop(0) ]  # next one in

        
        for line in lines:
                # strip out the httpheaders that come back at the start of a node connection
            logger.debug("doing: "+str([line]))
            if not self.httpheadersdone:
                if re.match("HTTP/", line):
                    assert not self.httpheaders
                    continue
                if line == "\r":
                    self.httpheadersdone = True
                    continue
                mheader = re.match("(.*?):\s*(.*)\r", line)
                if not mheader:
                    logger.error("Bad header: "+str([line]))
                else:
                    self.httpheaders.append((mheader.group(1), mheader.group(2)))
                continue

            logger.info("Recevied and will write: "+str([line]))
            self.client.writeall(line)
            if self.runobjectmaker:
                self.runobjectmaker.receiveline(line)


        # could move into a proper function in the client once slimmed down slightly
    def processEnded(self, reason):
        self.controllerconnection = None
        self.client.processrunning = None  # remove back connection
        del self.client.factory.runidclientmap[self.jdata["runid"]]

        sreason = str([reason])
        if sreason == "[<twisted.python.failure.Failure <class 'twisted.internet.error.ProcessDone'>>]":
            sreason = ""  # seems difficult to find the actual class type to compare with, but get rid of this "error" that really isn't an error
        elif sreason == "[<twisted.python.failure.Failure <class 'twisted.internet.error.ConnectionDone'>>]":
            sreason = ""  # seems difficult to find the actual class type to compare with, but get rid of this "error" that really isn't an error

        # other errors (eg connection lost) could put more useful errors into the client
        logger.debug("run process %s ended client# %d %s" % (self.client.clienttype, self.client.clientnumber, sreason))
    
        self.client.writeall(json.dumps({'message_type':'executionstatus', 'content':'runfinished', 'contentextra':sreason}))
        if self.runobjectmaker:
            self.runobjectmaker.schedulecompleted()
            
        if self.client.clienttype == "editing":
            self.client.factory.notifyMonitoringClients(self.client)
        elif self.client.clienttype == "scheduledrun":
            self.client.factory.scheduledruncomplete(self.client, reason.type==ProcessDone)

    def controllerconnectionrequestFailure(self, failure):
        logger.info("controllerconnectionrequest failure received "+str(failure))


# simply ciphers through the two functions
class ControllerConnectionProtocol(protocol.Protocol):
    def connectionLost(self, reason):
        #logger.debug("*** controller socket connection lost: "+str(reason))
        self.srunner.processEnded(reason)
        
    def dataReceived(self, data):
        #logger.debug("*** controller socket connection data: "+data)
        self.srunner.outReceived(data)


clientcreator = protocol.ClientCreator(reactor, ControllerConnectionProtocol)


# this is the new way that totally bypasses the dispatcher.  
# we reuse the spawnRunner class only for its user defined functions, not its processprotocol functions!
def MakeRunner(scrapername, guid, language, urlquery, username, code, client, beta_user, attachables, rev, bmakerunobject, agent):
    srunner = spawnRunner(client, code)  # reuse this class and its functions

    jdata = { }
    jdata["code"] = code.replace('\r', '')
    jdata["cpulimit"] = 80
    jdata["draft"] = (not username)   # or could be done by lack of presence of guid
    jdata["username"] = username   # comes through when done with stimulate_run, and we can use this for the dataproxy permissions (whether it can add to the attachables list)
    jdata["language"] = language
    jdata["scraperid"] = guid
    jdata["urlquery"] = urlquery
    jdata["scrapername"] = scrapername
    jdata["beta_user"] = beta_user
    jdata["attachables"] = attachables
    jdata["rev"] = rev

    # invent the runid (should actually
    jdata["runid"] = '%.6f_%s' % (time.time(), uuid.uuid4())
    if jdata.get("draft"):
       jdata["runid"] = "draft|||%s" % jdata["runid"]
    #logger.info(str(jdata))
    
    srunner.jdata = jdata
    if bmakerunobject:
        srunner.runobjectmaker = ScheduledRunMessageLoopHandler(client, username, agent,  jdata["runid"],rev)
        logger.info("Making run object on %s client# %d" % (scrapername, client.clientnumber))

    deferred = clientcreator.connectTCP(nodecontrollerhost, nodecontrollerport)
    deferred.addCallbacks(srunner.gotcontrollerconnectionprotocol, srunner.controllerconnectionrequestFailure)

    return srunner
    

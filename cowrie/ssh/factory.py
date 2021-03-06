# Copyright (c) 2009-2014 Upi Tamminen <desaster@gmail.com>
# See the COPYRIGHT file for more information

"""
This module contains ...
"""

import time

from twisted.conch.ssh import factory
from twisted.conch.ssh import keys
from twisted.python import log
from twisted.conch.openssh_compat import primes

from cowrie.ssh import connection
from cowrie.ssh import userauth
from cowrie.ssh import transport
from cowrie.core import keys as cowriekeys


class CowrieSSHFactory(factory.SSHFactory):
    """
    This factory creates HoneyPotSSHTransport instances
    They listen directly to the TCP port
    """

    services = {
        'ssh-userauth': userauth.HoneyPotSSHUserAuthServer,
        'ssh-connection': connection.CowrieSSHConnection,
        }
    starttime = None
    sessions = {}
    privateKeys = None
    publicKeys = None
    dbloggers = None
    output_plugins = None
    primes = None

    def __init__(self, cfg):
        self.cfg = cfg


    def logDispatch(self, *msg, **args):
        """
        Special delivery to the loggers to avoid scope problems
        """
        for dblog in self.dbloggers:
            dblog.logDispatch(*msg, **args)
        for output in self.output_plugins:
            output.logDispatch(*msg, **args)


    def startFactory(self):
        """
        """
        # Interactive protocols are kept here for the interact feature
        self.sessions = {}

        # For use by the uptime command
        self.starttime = time.time()

        # Load/create keys
        rsaPubKeyString, rsaPrivKeyString = cowriekeys.getRSAKeys(self.cfg)
        dsaPubKeyString, dsaPrivKeyString = cowriekeys.getDSAKeys(self.cfg)
        self.publicKeys = {
          'ssh-rsa': keys.Key.fromString(data=rsaPubKeyString),
          'ssh-dss': keys.Key.fromString(data=dsaPubKeyString)}
        self.privateKeys = {
          'ssh-rsa': keys.Key.fromString(data=rsaPrivKeyString),
          'ssh-dss': keys.Key.fromString(data=dsaPrivKeyString)}

        # Load db loggers
        self.dbloggers = []
        for x in self.cfg.sections():
            if not x.startswith('database_'):
                continue
            engine = x.split('_')[1]
            try:
                dblogger = __import__( 'cowrie.dblog.{}'.format(engine),
                    globals(), locals(), ['dblog']).DBLogger(self.cfg)
                log.addObserver(dblogger.emit)
                self.dbloggers.append(dblogger)
                log.msg("Loaded dblog engine: {}".format(engine))
            except:
                log.err()
                log.msg("Failed to load dblog engine: {}".format(engine))

        # Load output modules
        self.output_plugins = []
        for x in self.cfg.sections():
            if not x.startswith('output_'):
                continue
            engine = x.split('_')[1]
            try:
                output = __import__( 'cowrie.output.{}'.format(engine),
                    globals(), locals(), ['output']).Output(self.cfg)
                log.addObserver(output.emit)
                self.output_plugins.append(output)
                log.msg("Loaded output engine: {}".format(engine))
            except:
                log.err()
                log.msg("Failed to load output engine: {}".format(engine))

        factory.SSHFactory.startFactory(self)


    def stopFactory(self):
        """
        """
        factory.SSHFactory.stopFactory(self)
        for output in self.output_plugins:
            output.stop()


    def buildProtocol(self, addr):
        """
        Create an instance of the server side of the SSH protocol.

        @type addr: L{twisted.internet.interfaces.IAddress} provider
        @param addr: The address at which the server will listen.

        @rtype: L{cowrie.ssh.transport.HoneyPotSSHTransport}
        @return: The built transport.
        """

        _modulis = '/etc/ssh/moduli', '/private/etc/moduli'

        t = transport.HoneyPotSSHTransport()

        try:
            t.ourVersionString = self.cfg.get('honeypot', 'ssh_version_string')
        except:
            t.ourVersionString = "SSH-2.0-OpenSSH_6.0p1 Debian-4+deb7u2"

        t.supportedPublicKeys = list(self.privateKeys.keys())

        for _moduli in _modulis:
            try:
                self.primes = primes.parseModuliFile(_moduli)
                break
            except IOError as err:
                pass

        if not self.primes:
            ske = t.supportedKeyExchanges[:]
            if 'diffie-hellman-group-exchange-sha1' in ske:
                ske.remove('diffie-hellman-group-exchange-sha1')
                log.msg("No moduli, no diffie-hellman-group-exchange-sha1")
            if 'diffie-hellman-group-exchange-sha256' in ske:
                ske.remove('diffie-hellman-group-exchange-sha256')
                log.msg("No moduli, no diffie-hellman-group-exchange-sha256")
            t.supportedKeyExchanges = ske

        # Reorder supported ciphers to resemble current openssh more
        t.supportedCiphers = ['aes128-ctr', 'aes192-ctr', 'aes256-ctr',
            'aes128-cbc', '3des-cbc', 'blowfish-cbc', 'cast128-cbc',
            'aes192-cbc', 'aes256-cbc']
        t.supportedPublicKeys = ['ssh-rsa', 'ssh-dss']
        t.supportedMACs = ['hmac-md5', 'hmac-sha1']
        t.supportedCompressions = ['zlib@openssh.com', 'zlib', 'none']

        t.factory = self
        return t


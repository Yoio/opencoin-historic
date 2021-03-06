"""
Protocol have states, which are basically methods that consume messages, do
something and return messages. The states are just methods, and one state
might change the state of its protocol to another state. 

A protocol writes to a transport, using Transport.write. It receives messages
from the transport with Protocol.newMessage.

A state (a protocol method) returns messages, it does not write directly back
to a transport (XXX not sure about this, what if a state needs to communicate
with another enity). Instead newMessage by default writes back to the transport.
(XXX maybe the transport could take the returned message, and write it up its own,
ah write method?)

Before returning the message, the state should set the protocols state to the next
state (sounds a bit ackward, its easy, check the states code)
"""

from messages import Message
import containers    
import types

class Protocol:
    """A protocol ties messages and actions togehter, it is basically one side
       of an interaction. E.g. when A exchanges a coin with B, A would use the
       walletSenderProtocol, and B the walletRecipientProtocol."""

    def __init__(self):
        'Set the initial state'
        
        self.state = self.start
        self.result = None

    def setTransport(self,transport):
        'get the transport we are working with'
        
        self.transport = transport
        
    def start(self,message):
        'this should be the initial state of the protocol'
       
        pass

    def goodbye(self,message):
        self.state = self.finish
        return Message('GOODBYE')

    def finish(self,message):
        'always the last state. There can be other final states'        
        return Message('finished')
                    
    def newMessage(self,message):
        'this is used by a transport to pass on new messages to the protocol'

        out = self.state(message)
        self.transport.write(out)
        return out

    def newState(self,method):
        self.state = method

    def initiateHandshake(self,message):    
        self.newState(self.firstStep)
        return Message('HANDSHAKE',{'protocol': 'opencoin 1.0'})

#ProtocolErrorMessage = lambda x: Message('PROTOCOL_ERROR', 'send again %s' % x)
ProtocolErrorMessage = lambda x: Message('PROTOCOL_ERROR', 'send again')

class answerHandshakeProtocol(Protocol):


    def __init__(self,**mapping):
        Protocol.__init__(self)
        self.mapping = mapping

    def start(self,message):

        if message.type == 'HANDSHAKE':
            if message.data['protocol'] == 'opencoin 1.0':
                self.newState(self.dispatch)
                return Message('HANDSHAKE_ACCEPT')
            else:
                self.newState(self.goodbye)
                return Message('HANDSHAKE_REJECT','did not like the protocol version')
        else:
            return Message('PROTOCOL_ERROR','please do a handshake')


    def dispatch(self,message):        
        self.result = message
        nextprotocol = self.mapping[message.type]
        self.transport.setProtocol(nextprotocol)
        m = nextprotocol.newMessage(message)
        #print 'here ', m
        #return m




############################### Spending coins (w2w) ##########################
# Spoken bewteen two wallets to transfer coins / tokens                       #
###############################################################################

class TokenSpendSender(Protocol):
    """
    >>> from tests import coins
    >>> coin1 = coins[0][0]
    >>> coin2 = coins[1][0]
    >>> css = TokenSpendSender([coin1,coin2],'foobar')
    >>> css.state(Message(None))
    <Message('HANDSHAKE',{'protocol': 'opencoin 1.0'})>
    >>> css.state(Message('HANDSHAKE_ACCEPT'))
    <Message('SUM_ANNOUNCE',['...', '3', 'foobar'])>
    >>> css.state(Message('SUM_ACCEPT'))
    <Message('TOKEN_SPEND',['...', [[(...)], [(...)]], 'foobar'])>
    >>> css.state(Message('TOKEN_ACCEPT'))
    <Message('GOODBYE',None)>
    >>> css.state(Message('Really?'))
    <Message('finished',None)>
    """
    def __init__(self,coins,target):
        from containers import sumCurrencies

        self.coins = coins
        self.amount = sumCurrencies(coins)
        self.target = target
        
        import base64
        from crypto import _r as Random
        self.transaction_id = Random.getRandomString(128)
        self.encoded_transaction_id = base64.b64encode(self.transaction_id)

        Protocol.__init__(self)
        self.state = self.initiateHandshake

    def firstStep(self,message):       
        self.state = self.spendCoin
        standard_identifier = self.coins[0].standard_identifier # All the coins are
        currency_identifier = self.coins[0].currency_identifier # same currency & CDD
        return Message('SUM_ANNOUNCE',[self.encoded_transaction_id,
                                       standard_identifier,
                                       currency_identifier,
                                       str(self.amount),
                                       self.target])


    def spendCoin(self,message):
        if message.type == 'SUM_ACCEPT':
            self.state = self.goodbye            
            jsonCoins = [c.toPython() for c in self.coins]
            return Message('TOKEN_SPEND',[self.encoded_transaction_id,
                                          jsonCoins,
                                          self.target])
        elif message.type == 'PROTOCOL_ERROR':
            pass

        else:
            return ProtocolErrorMessage('TokenSpendSender')

    def goodbye(self,message):
        if message.type == 'TOKEN_ACCEPT':
            self.state = self.finish
            return Message('GOODBYE')

        elif message.type == 'PROTOCOL_ERROR':
            pass

        else:
            return ProtocolErrorMessage('TokenSpendSender')


class TokenSpendRecipient(Protocol):
    """
    >>> import entities
    >>> from tests import coins
    >>> coin1 = coins[0][0].toPython() # Denomination of 1
    >>> coin2 = coins[1][0].toPython() # Denomination of 2
    >>> w = entities.Wallet()
    >>> csr = TokenSpendRecipient(w)
    >>> csr.state(Message('SUM_ANNOUNCE',['1234','standard', 'currency', '3','a book']))
    <Message('SUM_ACCEPT',None)>
    >>> csr.state(Message('TOKEN_SPEND',['1234', [coin1, coin2], 'a book']))
    <Message('TOKEN_ACCEPT',None)>
    >>> csr.state(Message('Goodbye',None))
    <Message('GOODBYE',None)>
    >>> csr.state(Message('foobar'))
    <Message('finished',None)>

    TODO: Add PROTOCOL_ERROR checking
    """
    
    def __init__(self,wallet,issuer_transport = None):
        self.wallet = wallet
        self.issuer_transport = issuer_transport
        Protocol.__init__(self)

    def start(self,message):
        import base64
        from fraction import Fraction

        if message.type == 'SUM_ANNOUNCE':
            try:
                encoded_transaction_id, standard_identifier, currency_identifier, encoded_amount, self.target = message.data
            except ValueError:
                return ProtocolErrorMessage('SA')

            if not isinstance(encoded_transaction_id, types.StringType):
                return ProtocolErrorMessage('SA')

            if not isinstance(standard_identifier, types.StringType):
                return ProtocolErrorMessage('SA')

            if not isinstance(currency_identifier, types.StringType):
                return ProtocolErrorMessage('SA')

            if not isinstance(encoded_amount, types.StringType):
                return ProtocolErrorMessage('SA')

            if not isinstance(self.target, types.StringType):
                return ProtocolErrorMessage('SA')

            # Decode the transaction_id
            try:
                self.transaction_id = base64.b64decode(encoded_transaction_id)
            except TypeError:
                return ProtocolErrorMessage('SA')
            
            # Setup sum
            self.sum = Fraction(encoded_amount)

            # And do stuff
            #get some feedback from interface somehow
            action = self.wallet.confirmReceiveCoins('the other wallet id',self.sum,self.target)

            if action == 'reject':
                self.state = self.goodbye 
                return Message('SUM_REJECT')

            else:
                self.action = action
                self.state = self.handleCoins
                return Message('SUM_ACCEPT')

        elif message.type == 'PROTOCOL_ERROR':
            pass

        else:
            return ProtocolErrorMessage('TokenSpendRecipient')

    def handleCoins(self,message):
        import base64

        if message.type == 'TOKEN_SPEND':
            try:
                encoded_transaction_id, tokens, target = message.data
            except ValueError:
                return ProtocolErrorMessage('TS')

            if not isinstance(encoded_transaction_id, types.StringType):
                return ProtocolErrorMessage('TS')

            
            if not isinstance(tokens, types.ListType):
                return ProtocolErrorMessage('TS')
            
            if not tokens: # We require tokens
                return ProtocolErrorMessage('TS')
            for token in tokens:
                if not isinstance(token, types.ListType):
                    return ProtocolErrorMessage('TS')

            # Convert transaction_id
            try:
                transaction_id = base64.b64decode(encoded_transaction_id)
            except TypeError:
                return ProtocolErrorMessage('TS')

            # Convert the tokens
            try:
                tokens = [containers.CurrencyCoin().fromPython(c) for c in tokens]
            except AttributeError: #FIXME: this is the wrong error, I'm pretty sure
                return ProtocolErrorMessage('TS')

            
            # And now do things
            from containers import sumCurrencies

            #be conservative
            result = Message('TOKEN_REJECT','default')
            
            if transaction_id != self.transaction_id:
                #FIXME: is the a PROTOCOL_ERROR?
                result = Message('TOKEN_REJECT','Rejected')

            elif sumCurrencies(tokens) != self.sum:
                result = Message('TOKEN_REJECT','Rejected')
            
            elif target != self.target:
                result = Message('TOKEN_REJECT','Rejected')
            
            elif self.action in ['redeem','exchange','trust']:
                out = self.wallet.handleIncomingCoins(tokens,self.action,target)
                if out:
                    result = Message('TOKEN_ACCEPT')

            self.state = self.goodbye
            return result

        elif message.type == 'PROTOCOL_ERROR':
            pass

        else:
            return ProtocolErrorMessage('TokenSendRecipient')




############################### Transfer tokens  ##############################
# This is spoken between a wallet (sender) and the issuer, for minting,       #
# exchange and redemption                                                     #
###############################################################################

class TransferTokenSender(Protocol):
    """
    >>> from tests import coins
    >>> coin1 = coins[0][0] # denomination of 1
    >>> coin2 = coins[1][0] # denomination of 2

    >>> tts = TransferTokenSender('my account',[],[coin1, coin2],type='redeem')
    >>> tts.state(Message(None))
    <Message('HANDSHAKE',{'protocol': 'opencoin 1.0'})>
    >>> tts.state(Message('HANDSHAKE_ACCEPT'))
    <Message('TRANSFER_TOKEN_REQUEST',['...', 'my account', [], [[(...)], [(...)]], [['type', 'redeem']]])>
    >>> tts.state(Message('TRANSFER_TOKEN_ACCEPT',[tts.encoded_transaction_id, []]))
    <Message('GOODBYE',None)>

    """

    def __init__(self, target, blinds, coins, **kwargs):
        import base64
        from crypto import _r as Random
        self.transaction_id = Random.getRandomString(128)
        self.encoded_transaction_id = base64.b64encode(self.transaction_id)

        self.target = target
        self.blinds = blinds
        self.coins = [c.toPython() for c in coins]
        self.kwargs = kwargs

        Protocol.__init__(self)
        self.state = self.initiateHandshake
   
    def firstStep(self,message):
        data = [self.encoded_transaction_id,
                self.target,
                self.blinds,
                self.coins]
        if self.kwargs:
            data.append([list(i) for i in self.kwargs.items()])                
        self.state = self.goodbye
        return Message('TRANSFER_TOKEN_REQUEST',data)

    def goodbye(self,message):
        import base64

        if message.type == 'TRANSFER_TOKEN_ACCEPT':

            try:
                encoded_transaction_id, blinds = message.data
            except ValueError:
                return ProtocolErrorMessage('TTA')

            if not isinstance(blinds, types.ListType):
                return ProtocolErrorMessage('TTA')
            for blind in blinds:
                if not isinstance(blind, types.StringType):
                    return ProtocolErrorMessage('TTA')
        
            # decode the blinds
            try:
                self.blinds = [base64.b64decode(blind) for blind in blinds]
            except TypeError:
                return ProtocolErrorMessage('TTA')

            #decode transaction_id
            try:
                transaction_id = base64.b64decode(encoded_transaction_id)
            except TypeError:
                return ProtocolErrorMessage('TTA')

            # Start checking things
            if transaction_id != self.transaction_id:
                #FIXME: Wrong message, I think. We don't really have a way to handle this.
                return Message('PROTOCOL_ERROR', 'incorrect transaction_id')
        

            if self.kwargs['type'] == 'exchange' or self.kwargs['type'] == 'mint':
                if not blinds:
                    return ProtocolErrorMessage('TTA')

            else:
                if len(blinds) != 0:
                    raise Exception('c')
                    return ProtocolErrorMessage('TTA')
                
            self.result = 1
                
        elif message.type == 'TRANSFER_TOKEN_DELAY':
            try:
                encoded_transaction_id, reason = message.data
            except ValueError:
                return ProtocolErrorMessage('TTD')

            if not isinstance(reason, types.StringType):
                return ProtocolErrorMessage('TTD')

            # Decode the transaction_id
            try:
                transaction_id = base64.b64decode(encoded_transaction_id)
            except TypeError:
                return ProtocolErrorMessage('TTD')

            # Start checking things
            if transaction_id != self.transaction_id:
                #FIXME: This seems like a wrong message....
                return ProtocolErrorMessage('TTD')

            # FIXME Do some things here, after we work out how delays work
                
            self.result = 1

        elif message.type == 'TRANSFER_TOKEN_REJECT':
            try:
                encoded_transaction_id, type, reason, reason_detail = message.data
            except ValueError:
                return ProtocolErrorMessage('TTRj')

            if not isinstance(encoded_transaction_id, types.StringType):
                return ProtocolErrorMessage('TTRj')
            
            if not isinstance(type, types.StringType):
                return ProtocolErrorMessage('TTRj')
            if not type:
                return ProtocolErrorMessage('TTRj')

            if not isinstance(reason, types.StringType):
                return ProtocolErrorMessage('TTRj')
            if not reason:
                return ProtocolErrorMessage('TTRj')
            
            if not isinstance(reason_detail, types.ListType):
                return ProtocolErrorMessage('TTRj')
            

            # Decode the transaction_id
            try:
                transcation_id = base64.b64decode(encoded_transaction_id)
            except TypeError:
                return ProtocolErrorMessage('TTRj')

            # Do checking of reason_detail
            # If reason is see dtail, reason_detail is a list with
            # entries, otherwise, reason_detail is an empty list
            if reason == 'See detail':
                if not reason_detail:
                    return ProtocolErrorMessage('TTRj')
            else:
                if reason_detail:
                    return ProtocolErrorMessage('TTRj')
            
            # Any checking of specific reasons for validity should be also
            # be done, but reason_detail is always empty 

            # Start checking things
            if transaction_id != self.transaction_id:
                #FIXME: I don't like using this message for this..
                return ProtocolErrorMessage('TTRj')

            # FIXME: Do something here?

            self.result = 0

        elif message.type == 'PROTOCOL_ERROR':
            #FIXME: self.state=self.finish is hackish. Does it do what we want?
            self.state = self.finish
            return Message('GOODBYE')

        else:
            return ProtocolErrorMessage('TransferTokenSender')

        self.state = self.finish
        return Message('GOODBYE')


class TransferTokenRecipient(Protocol):
    """
    >>> import entities, tests, containers, base64, copy, calendar
    >>> issuer = tests.makeIssuer()
    >>> issuer.getTime = lambda: calendar.timegm((2008,01,31,0,0,0)) 
    >>> issuer.mint.getTime = issuer.getTime

    >>> ttr = TransferTokenRecipient(issuer)
    >>> coin1 = tests.coins[0][0].toPython() # denomination of 1
    >>> coin2 = tests.coins[1][0].toPython() # denomination of 2
    
    >>> coin3 = tests.coins[0][0].toPython() # denomination of 1

    This should not be accepted
    >>> ttr.state(Message('TRANSFER_TOKEN_REQUEST',['1234', 'my account', [], ['foobar'], [['type', 'redeem']]]))    
    <Message('PROTOCOL_ERROR','send again')>

    The malformed coin should be rejected
    >>> malformed = copy.deepcopy(tests.coins[0][0])
    >>> malformed.signature = 'Not a valid signature'
    >>> ttr.state(Message('TRANSFER_TOKEN_REQUEST',['1234', 'my account', [], [malformed.toPython()], [['type', 'redeem']]]))
    <Message('TRANSFER_TOKEN_REJECT',['1234', 'Token', 'See detail', ['Rejected']])>

    The unknown key_identifier should be rejected
    >>> malformed = copy.deepcopy(tests.coins[0][0])
    >>> malformed.key_identifier = 'Not a valid key identifier'
    >>> ttr.state(Message('TRANSFER_TOKEN_REQUEST',['1234', 'my account', [], [malformed.toPython()], [['type', 'redeem']]]))
    <Message('TRANSFER_TOKEN_REJECT',['1234', 'Token', 'See detail', ['Rejected']])>

    >>> ttr.state(Message('TRANSFER_TOKEN_REQUEST',['1234', 'my account', [], [coin1, coin2], [['type', 'redeem']]]))
    <Message('TRANSFER_TOKEN_ACCEPT',['1234', []])>

    Try to double spend. Should not work.
    >>> ttr.state = ttr.start 
    >>> ttr.state(Message('TRANSFER_TOKEN_REQUEST',['1234', 'my account', [], [coin1, coin2], [['type', 'redeem']]]))
    <Message('TRANSFER_TOKEN_REJECT',['1234', 'Token', 'Invalid token', []])>

    >>> blank1 = containers.CurrencyBlank().fromPython(tests.coinA.toPython(nosig=1))
    >>> blank2 = containers.CurrencyBlank().fromPython(tests.coinB.toPython(nosig=1))
    >>> blind1 = base64.b64encode(blank1.blind_blank(tests.CDD,tests.mint_key1, blind_factor='a'*26))
    >>> blind2 = base64.b64encode(blank2.blind_blank(tests.CDD,tests.mint_key2, blind_factor='a'*26))
    >>> blindslist = [[tests.mint_key1.encodeField('key_identifier'),[blind1]],
    ...               [tests.mint_key2.encodeField('key_identifier'),[blind2]]]

    >>> ttr.state = ttr.start
    >>> ttr.state(Message('TRANSFER_TOKEN_REQUEST',['1234', 'my account', blindslist, [], [['type', 'mint']]]))
    <Message('TRANSFER_TOKEN_ACCEPT',['1234', ['Do0el3uxdyFMF8NdXtowBLBOxXM0r7xR9hXkaZWEhPUBQCe8yaYGO09wnxrWEVFlt0r9M6bCZxKtzNGDGw3/XQ==', 'dTnL8yTkdelG9fW//ZoKzUl7LTjBXiElaHkfyMLgVetEM7pmEzfcdfRWhm2PP3IhnkZ8CmAR1uOJ99rJ+XBASA==']])>

    Now, check to make sure the implementation is good
    >>> ttr.state = ttr.start
    >>> ttr.state(Message('TRANSFER_TOKEN_REQUEST'))
    <Message('PROTOCOL_ERROR','send again')>

    Okay. Have to reset DSDB to do this next trick
    >>> issuer = tests.makeIssuer()
    >>> issuer.getTime = lambda: calendar.timegm((2008,01,31,0,0,0)) 
    >>> issuer.mint.getTime = issuer.getTime
    >>> blank = tests.makeBlank(tests.mintKeys[0], 'a'*26, 'a'*26)
    >>> blind = [[tests.mintKeys[0].encodeField('key_identifier'), [base64.b64encode(blank.blind_blank(tests.CDD, tests.mintKeys[0]))]]]
    >>> ttr = TransferTokenRecipient(issuer)
    >>> ttr.state = ttr.start
    >>> ttr.state(Message('TRANSFER_TOKEN_REQUEST',['1234', '', blind, [coin1], [['type', 'exchange']]]))
    <Message('TRANSFER_TOKEN_ACCEPT',['1234', ['UIo2KtqK/6JqSWbtFFVR14fOjnzwr4tDiY/6kOnQ0h92EewY2vJBV2XaS43wK3RsNFg0sHzNh3v2BVDFV8cDvQ==']])>

    """

    def __init__(self,issuer):
        self.issuer = issuer
        Protocol.__init__(self)

    def start(self,message):
        from entities import LockingError
        import base64
        
        if message.type == 'TRANSFER_TOKEN_REQUEST':
            try:
                encoded_transaction_id, target, blindslist, coins, options_list = message.data
            except TypeError:
                return ProtocolErrorMessage('TTRq17')

            if not isinstance(target, types.StringType):
                return ProtocolErrorMessage('TTRq1')

            if not isinstance(blindslist, types.ListType):
                return ProtocolErrorMessage('TTRq2')

            for blind in blindslist:
            
                if not isinstance(blind, types.ListType):
                    return ProtocolErrorMessage('TTRq3')
                try:
                    key, b = blind
                except ValueError:
                    return ProtocolErrorMessage('TTRq4')
                
                if not isinstance(key, types.StringType):
                    return ProtocolErrorMessage('TTRq5')
                
                if not isinstance(b, types.ListType):
                    return ProtocolErrorMessage('TTRq6')
                
                for blindstring in b:
                    if not isinstance(blindstring, types.StringType):
                        return ProtocolErrorMessage('TTRq7')
                if len(b) == 0:
                    return ProtocolErrorMessage('TTRq14')

            # Decode transaction_id
            try:
                transaction_id = base64.b64decode(encoded_transaction_id)
            except TypeError:
                return ProtocolErrorMessage('TTRq18')

            # Convert blindslist
            try:
                blindslist = [[base64.b64decode(key), [base64.b64decode(bl) for bl in blinds]] for key, blinds in blindslist]
            except TypeError:
                return ProtocolErrorMessage('TTRq15')

            if not isinstance(coins, types.ListType):
                return ProtocolErrorMessage('TTRq8')
            
            for coin in coins:
                if not isinstance(coin, types.ListType):
                    return ProtocolErrorMessage('TTRq9')

            #convert coins
            try:
                coins = [containers.CurrencyCoin().fromPython(c) for c in coins]
            except AttributeError: #FIXME: Right error?
                return ProtocolErrorMessage('TTRq16')

            if not isinstance(options_list, types.ListType):
                return ProtocolErrorMessage('TTRq10')
            
            for options in options_list:
                try:
                    key, val = options
                except ValueError:
                    return ProtocolErrorMessage('TTRq11')
            
                if not isinstance(key, types.StringType):
                    return ProtocolErrorMessage('TTRq12')
                
                if not isinstance(val, types.StringType):
                    return ProtocolErrorMessage('TTRq13')

            # Decipher options
            options = {}
            options.update(options_list)

            if not options.has_key('type'):
                return Message('TRANSFER_TOKEN_REJECT', 'Options', 'Reject', [])
            
            # Start doing things
            if options['type'] == 'redeem':

                failures = []

                #check if coins are valid
                for coin in coins:
                    mintKey = self.issuer.keyids.get(coin.key_identifier, None)
                    if not mintKey or not coin.validate_with_CDD_and_MintKey(self.issuer.cdd, mintKey):
                        failures.append(coin)
                
                if failures: # We don't know exactly how, so give coin by coin information
                    details = []
                    for coin in coins:
                        if coin not in failures:
                            details.append('None')
                        else:
                            details.append('Rejected')
                    return Message('TRANSFER_TOKEN_REJECT', [encoded_transaction_id, 'Token',
                                   'See detail', details])

                #and not double spent
                try:
                    #XXX have adjustable time for lock
                    self.issuer.dsdb.lock(transaction_id,coins,86400)
                except LockingError, e:
                    return Message('TRANSFER_TOKEN_REJECT', [encoded_transaction_id, 'Token', 'Invalid token', []])
                
                # XXX transmit funds
                
                if not self.issuer.transferToTarget(target,coins):
                    self.issuer.dsdb.unlock(transaction_id)
                    return ProtocolErrorMessage('TTRq19')

                #register them as spent
                try:
                    self.issuer.dsdb.spend(transaction_id,coins)
                except LockingError, e: 
                    #Note: if we fail here, that means we have large problems, since the coins are locked
                    return ProtocolErrorMessage('TTRq20')

                self.state = self.goodbye
                return Message('TRANSFER_TOKEN_ACCEPT',[encoded_transaction_id, []])


            # exchange uses basically mint and redeem (or a modified form thereof)
            # XXX refactor to not have duplicate code
            


            elif options['type'] == 'mint':

                #check that we have the keys
                blinds = [[self.issuer.keyids[keyid], blinds] for keyid, blinds in blindslist]

                #check the MintKeys for validity
                timeNow = self.issuer.getTime()
                failures = []
                for mintKey, blindlist in blinds:
                    can_mint, can_redeem = mintKey.verify_time(timeNow)
                    if not can_mint:
                        # TODO: We need more logic here. can_mint only specifies if we are
                        # between not_before and key_not_after. We may also need to do the
                        # checking of the period of time the mint can mint but the IS cannot
                        # send the key to the mint.
                        failures.append(mintKey.encodeField('key_identifier'))

                if failures:
                    return Message('TRANSFER_TOKEN_REJECT', [encoded_transaction_id, 'Blind', 'Invalid key_identifier', []])

                #check target
                if not self.issuer.debitTarget(target,blindslist):
                    return ProtocolErrorMessage('TTRq20')


                #mint them immediately (the only thing we can do right now with the mint)
                minted = []
                for key, blindlist in blinds:
                    this_set = []
                    for blind in blindlist:
                        signature = self.issuer.mint.signNow(key.key_identifier, blind)
                        this_set.append(base64.b64encode(signature))

                    minted.extend(this_set)
                    
                return Message('TRANSFER_TOKEN_ACCEPT', [encoded_transaction_id, minted])
                
            elif options['type'] == 'exchange':
                import base64

                failures = []

                #check if coins are valid
                for coin in coins:
                    mintKey = self.issuer.keyids.get(coin.key_identifier, None)
                    try: 
                        if not mintKey or not coin.validate_with_CDD_and_MintKey(self.issuer.cdd, mintKey):
                            failures.append(coin)
                    except AttributeError:
                        failures.append(coin)
                
                if failures: # We don't know exactly how, so give coin by coin information
                    details = []
                    for coin in coins:
                        if coin not in failures:
                            details.append('None')
                        else:
                            details.append('Rejected')
                    return Message('TRANSFER_TOKEN_REJECT', [encoded_transaction_id, 'Token',
                                   'See detail', details])

                #and not double spent
                try:
                    self.issuer.dsdb.lock(transaction_id,coins,86400)
                except LockingError, e:
                    return Message('TRANSFER_TOKEN_REJECT', [encoded_transaction_id, 'Token', 'Invalid token', []])
                
                # And onto the blinds

                #check that we have the keys
                import base64
                blinds = [[self.issuer.keyids[keyid], blinds] for keyid, blinds in blindslist]

                #check target
                if not self.issuer.debitTarget(target,blindslist):
                    self.issuer.dsdb.unlock(transaction_id)
                    return Message('PROTOCOL_ERROR', 'send again')

                #check the MintKeys for validity
                timeNow = self.issuer.getTime()
                failures = []
                for mintKey, blindlist in blinds:
                    can_mint, can_redeem = mintKey.verify_time(timeNow)
                    if not can_mint:
                        # TODO: We need more logic here. can_mint only specifies if we are
                        # between not_before and key_not_after. We may also need to do the
                        # checking of the period of time the mint can mint but the IS cannot
                        # send the key to the mint.
                        failures.append(mintKey.encodeField('key_identifier'))

                if failures:
                    self.issuer.dsdb.unlock(transaction_id)
                    return Message('TRANSFER_TOKEN_REJECT', [encoded_transaction_id, 'Blind', 'Invalid key_identifier', []])

                # Make sure that we have the same amount of coins as mintings
                from fraction import Fraction
                from containers import sumCurrencies

                total = Fraction('0')
                for b in blinds:
                    total += b[0].denomination * len(b[1])

                if total != sumCurrencies(coins):
                    self.issuer.dsdb.unlock(transaction_id)
                    return Message('TRANSFER_TOKEN_REJECT', [encoded_transaction_id, 'Generic', 'Rejected', []])

                # mint them immediately (the only thing we can do right now with the mint)
                minted = []
                from entities import MintError
                for key, blindlist in blinds:
                    this_set = []
                    for blind in blindlist:
                        try:
                            signature = self.issuer.mint.signNow(key.key_identifier, blind)
                        except MintError:
                            self.issuer.dsdb.unlock(transaction_id)
                            return Message('TRANSFER_TOKEN_REJECT', [encoded_transaction_id, 'Blind', 'Unable to sign', []])
                        this_set.append(base64.b64encode(signature))

                    minted.extend(this_set)

                # And now, we have verified the coins are valid, they aren't double spent, and we've minted.

                # Register the tokens as spent
                try:
                    self.issuer.dsdb.spend(transaction_id,coins)
                except LockingError, e: 
                    #Note: if we fail here, that means we have large problems, since the coins are locked
                    return Message('PROTOCOL_ERROR', 'send again')

                self.state = self.goodbye

                return Message('TRANSFER_TOKEN_ACCEPT', [encoded_transaction_id, minted])


            else:
                #FIXME: This could rightfully be a PROTOCOL_ERROR, since we don't have a 'type' that we like.
                # -or- maybe we should check to see if we set it, and if we didn't then do a PROTOCOL_ERROR
                return Message('TRANSFER_TOKEN_REJECT', ['Option', 'Rejected', []])

        elif message.type == 'TRANSFER_TOKEN_RESUME':
            encoded_transaction_id = message.data

            if not isinstance(encoded_transaction_id, types.StringType):
                return ProtocolErrorMessage('TTRs')

            # Decode transaction_id
            try:
                transaction_id = base64.b64decode(encoded_transaction_id)
            except TypeError:
                return ProtocolErrorMessage('TTRs')

            # FIXME: actually handle TRANSFER_TOKEN_RESUMES

        elif message.type == 'PROTOCOL_ERROR':
            #FIXME: actually do something for a PROTOCOL_ERROR
            pass

        else:
            return ProtocolErrorMessage('TransferTokenRecipient')




############################### Mint key exchange #############################
#Between a wallet and the IS, to get the mint key                             #
###############################################################################

class fetchMintingKeyProtocol(Protocol):
    """
    Used by a wallet to fetch the mints keys, needed when 
    creating blanks
       
    Lets fetch by denomination

    >>> fmp = fetchMintingKeyProtocol(denominations=['1'])
    >>> fmp.state(Message(None))
    <Message('HANDSHAKE',{'protocol': 'opencoin 1.0'})>

    >>> fmp.state(Message('HANDSHAKE_ACCEPT'))
    <Message('MINTING_KEY_FETCH_DENOMINATION',[['1'], '0'])>

    >>> from tests import mintKeys
    >>> mintKey = mintKeys[0]
    >>> fmp.state(Message('MINTING_KEY_PASS',[mintKey.toPython()]))
    <Message('GOODBYE',None)>


    And now by keyid

    >>> fmp = fetchMintingKeyProtocol(keyids=['sj17RxE1hfO06+oTgBs9Z7xLut/3NN+nHJbXSJYTks0='])
    >>> fmp.state(Message(None))
    <Message('HANDSHAKE',{'protocol': 'opencoin 1.0'})>

    >>> fmp.state(Message('HANDSHAKE_ACCEPT'))
    <Message('MINTING_KEY_FETCH_KEYID',['sj17RxE1hfO06+oTgBs9Z7xLut/3NN+nHJbXSJYTks0='])>

    >>> fmp.state(Message('MINTING_KEY_PASS',[mintKey.toPython()]))
    <Message('GOODBYE',None)>


    Lets have some problems a failures (we set the state
    to getKey to reuse the fmp object and save a couple
    of lines)

    >>> fmp.newState(fmp.getKey)
    >>> fmp.state(Message('MINTING_KEY_FAILURE',[['RxE1', 'Unknown key_identifier']]))
    <Message('GOODBYE',None)>
   
    Now lets break something
    
    >>> fmp.newState(fmp.getKey)
    >>> fmp.state(Message('FOOBAR'))
    <Message('PROTOCOL_ERROR','send again')>

    Okay. Now we'll test every possible MINTING_KEY_PASS.
    The correct argument is a list of coins. Try things to
    break it.
    
    >>> fmp.newState(fmp.getKey)
    >>> fmp.state(Message('MINTING_KEY_PASS', [['foo']]))
    <Message('PROTOCOL_ERROR','send again')>

    >>> fmp.newState(fmp.getKey)
    >>> fmp.state(Message('MINTING_KEY_PASS', ['foo']))
    <Message('PROTOCOL_ERROR','send again')>

    >>> fmp.newState(fmp.getKey)
    >>> fmp.state(Message('MINTING_KEY_PASS', 'foo'))
    <Message('PROTOCOL_ERROR','send again')>

    >>> fmp.newState(fmp.getKey)
    >>> fmp.state(Message('MINTING_KEY_PASS', []))
    <Message('PROTOCOL_ERROR','send again')>

    Now try every possible bad MINTING_KEY_FAILURE.
    Note: it may make sense to verify we have tood reasons
    as well.

    We need to make sure we are setup as handling keyids
    >>> fmp.keyids and not fmp.denominations
    True

    Check base64 decoding causes failure
    >>> fmp.newState(fmp.getKey)
    >>> fmp.state(Message('MINTING_KEY_FAILURE', [[1, '']]))
    <Message('PROTOCOL_ERROR','send again')>

    And the normal tests
    >>> fmp.newState(fmp.getKey)
    >>> fmp.state(Message('MINTING_KEY_FAILURE', [[]]))
    <Message('PROTOCOL_ERROR','send again')>
    
    Okay. Check the denomination branch now
    
    >>> fmp.denominations = ['1']
    >>> fmp.keyids = None

    Make sure we are in the denomination branch
    >>> fmp.newState(fmp.getKey)
    >>> fmp.state(Message('MINTING_KEY_FAILURE', [['1', '']]))
    <Message('GOODBYE',None)>
    
    Do a check

    >>> fmp.newState(fmp.getKey)
    >>> fmp.state(Message('MINTING_KEY_FAILURE', [[]]))
    <Message('PROTOCOL_ERROR','send again')>
    
    """

    def __init__(self,denominations=None,keyids=None,time=None):
        
        self.denominations = denominations
        self.keyids = keyids
        self.keycerts = []

        if not time: # The encoded value of time
            self.encoded_time = '0'
        else:
            self.encoded_time = containers.encodeTime(time)

        Protocol.__init__(self)

    def start(self,message):
        self.newState(self.requestKey)
        return Message('HANDSHAKE',{'protocol':'opencoin 1.0'})

    def requestKey(self,message):
        """Completes handshake, asks for the minting keys """

        if message.type == 'HANDSHAKE_ACCEPT':
            
            if self.denominations:
                self.newState(self.getKey)
                return Message('MINTING_KEY_FETCH_DENOMINATION',[self.denominations, self.encoded_time])
            elif self.keyids:
                self.newState(self.getKey)
                return Message('MINTING_KEY_FETCH_KEYID',self.keyids) 

        elif message.type == 'HANDSHAKE_REJECT':
            self.newState(self.finish)
            return Message('GOODBYE')

        else:
            return Message('PROTOCOL ERROR','send again')

    def getKey(self,message):
        """Gets the actual key"""

        if message.type == 'MINTING_KEY_PASS':

            if not isinstance(message.data, types.ListType):
                return ProtocolErrorMessage('MKP1')
            
            if len(message.data) == 0: # Nothing in the message
                return ProtocolErrorMessage('MKP2')

            try:
                keys = [containers.MintKey().fromPython(key) for key in message.data]
            except AttributeError: #FIXME: Correct error?
                return ProtocolErrorMessage('MKP3')
            except TypeError:
                return ProtocolErrorMessage('MKP4')
            except IndexError:
                return ProtocolErrorMessage('MKP5')

            #TODO: Check to make sure we got the keys we asked for, probably?

            # Note: keycerts stores the value of the MintKeys. They get checked by the
            # wallet explicitly
            self.keycerts.extend(keys)
            
            self.newState(self.finish)
            return Message('GOODBYE')
                

        elif message.type == 'MINTING_KEY_FAILURE':
            reasons = message.data

            if not isinstance(reasons, types.ListType):
                return ProtocolErrorMessage('MKF1')
            if not reasons:
                return ProtocolErrorMessage('MKF2')

            for reasonlist in reasons:
                if not isinstance(reasonlist, types.ListType):
                    return ProtocolErrormessage('MKF3')

                try:
                    key, rea = reasonlist
                except ValueError:
                    return ProtocolErrorMessage('MKF4')

                if not isinstance(key, types.StringType):
                    return ProtocolErrorMessage('MKF5')
                if not isinstance(rea, types.StringType):
                    return ProtocolErrorMessage('MKF6')

                # Do not do any conversions of keyid/denomination at this time. Have
                # to wait to do it after we know which set we have

            self.reasons = []
            if self.denominations: # Was a denomination search
                for reasonlist in message.data:
                    denomination, reason = reasonlist
                        
                    #FIXME: Should we make sure valid reason?
                    #FIXME: Did we even ask for this denomination?
                    self.reasons.append((denomination, reason))

            else: # Was a key_identifier search
                import base64
                for reasonlist in message.data:
                    key, reason = reasonlist
                        
                    #FIXME: Should we make sure valid reason?
                    #FIXME: Did we even ask for this denomination
                    # Note: Explicit b64decode here
                    try:
                        self.reasons.append((base64.b64decode(key), reason))
                    except TypeError:
                        return ProtocolErrorMessage('MKF9')

            self.newState(self.finish)
            return Message('GOODBYE')
        
        elif message.type == 'PROTOCOL_ERROR':
            pass

        else:
            return ProtocolErrorMessage('fetchMintingKeyProtocol')



class giveMintingKeyProtocol(Protocol):
    """An issuer hands out a key. The other side of fetchMintingKeyProtocol.
    >>> from entities import Issuer
    >>> issuer = Issuer()
    >>> issuer.createMasterKey(keylength=512)
    >>> issuer.makeCDD(currency_identifier='http://opencent.net/OpenCent2', denominations=['1', '2'],
    ...                short_currency_identifier='OC', options=[], issuer_service_location='here')
    >>> now = 0; later = 1; much_later = 2
    >>> pub1 = issuer.createSignedMintKey('1', now, later, much_later)
    >>> gmp = giveMintingKeyProtocol(issuer)
    
    >>> gmp.state(Message('HANDSHAKE',{'protocol': 'opencoin 1.0'}))
    <Message('HANDSHAKE_ACCEPT',None)>

    >>> gmp.state(Message('MINTING_KEY_FETCH_DENOMINATION',[['1'], '0']))
    <Message('MINTING_KEY_PASS',[[('key_identifier', '...'), ('currency_identifier', 'http://opencent.net/OpenCent2'), ('denomination', '1'), ('not_before', '...T...Z'), ('key_not_after', '...T...Z'), ('token_not_after', '...T...Z'), ('public_key', '...,...'), ['signature', [('keyprint', '...'), ('signature', '...')]]]])>

    >>> gmp.newState(gmp.giveKey)
    >>> m = gmp.state(Message('MINTING_KEY_FETCH_KEYID',[pub1.encodeField('key_identifier')]))
    >>> m
    <Message('MINTING_KEY_PASS',[...])>

    >>> gmp.newState(gmp.giveKey)
    >>> gmp.state(Message('MINTING_KEY_FETCH_DENOMINATION',[['2'], '0']))
    <Message('MINTING_KEY_FAILURE',[['2', 'Unknown denomination']])>
   

    >>> gmp.newState(gmp.giveKey)
    >>> gmp.state(Message('MINTING_KEY_FETCH_KEYID',['NonExistantIDxxx']))
    <Message('MINTING_KEY_FAILURE',[['NonExistantIDxxx', 'Unknown key_identifier']])>

    >>> gmp.newState(gmp.giveKey)
    >>> gmp.state(Message('bla','blub'))
    <Message('PROTOCOL_ERROR','send again')>

    """

    def __init__(self,issuer):
        
        self.issuer = issuer
        Protocol.__init__(self)


    def start(self,message):

        if message.type == 'HANDSHAKE':
            if message.data['protocol'] == 'opencoin 1.0':
                self.newState(self.giveKey)
                return Message('HANDSHAKE_ACCEPT')
            else:
                self.newState(self.goodbye)
                return Message('HANDSHAKE_REJECT','did not like the protocol version')
        else:
            return Message('PROTOCOL_ERROR','please do a handshake')


    def giveKey(self,message):
    
        self.newState(self.goodbye)

        errors = []
        keys = []

        if message.type == 'MINTING_KEY_FETCH_DENOMINATION':
            try:
                denominations, time = message.data
            except ValueError: # catch tuple unpack errors
                return Message('PROTOCOL_ERROR', 'send again')

            if not isinstance(denominations, types.ListType):
                return ProtocolErrorMessage('MKFD')
            if not denominations: # no denominations sent
                return ProtocolErrorMessage('MKFD')
            for denomination in denominations:
                if not isinstance(denomination, types.StringType):
                    return ProtocolErrorMessage('MKFD')

            if not isinstance(time, types.StringType):
                return ProtocolErrorMessage('MKFD')


            if time == '0':
                time = self.issuer.getTime()
            else:
                try:
                    time = containers.decodeTime(time)
                except ValueError:
                    return ProtocolErrorMessage('MKFD')
                
            for denomination in denominations:
                try:
                    key = self.issuer.getKeyByDenomination(denomination, time)            
                    keys.append(key)
                except 'KeyFetchError': 
                    errors.append([denomination, 'Unknown denomination'])
        
        elif message.type == 'MINTING_KEY_FETCH_KEYID':                

            import base64

            encoded_keyids = message.data
            
            if not isinstance(encoded_keyids, types.ListType):
                return ProtocolErrorMessage('MKFK1')
            if not encoded_keyids:
                return ProtocolErrorMessage('MKFK2')
            for encoded_keyid in encoded_keyids:
                if not isinstance(encoded_keyid, types.StringType):
                    return ProtocolErrorMessage('MKFK3')
            
            # Decode keyids
            try:
                keyids = [base64.b64decode(keyid) for keyid in encoded_keyids]
            except TypeError:
                return ProtocolErrorMessage('MKFK4')

            for keyid in keyids:
                try:
                    key = self.issuer.getKeyById(keyid)
                    keys.append(key)
                except 'KeyFetchError':                
                    errors.append([base64.b64encode(keyid), 'Unknown key_identifier'])
        
        else:
            return Message('PROTOCOL_ERROR', 'send again')

        if not errors:            
            return Message('MINTING_KEY_PASS',[key.toPython() for key in keys])
        else:
            return Message('MINTING_KEY_FAILURE',errors)

############################### For testing ########################################

class WalletSenderProtocol(Protocol):
    """
    This is just a fake protocol, just showing how it works

    >>> sp = WalletSenderProtocol(None)
   
    It starts with sending some money
    >>> sp.state(Message(None))
    <Message('sendMoney',[1, 2])>
    
    >>> sp.state(Message('Foo'))
    <Message('Please send a receipt',None)>

    Lets give it a receipt
    >>> sp.state(Message('Receipt'))
    <Message('Goodbye',None)>

    >>> sp.state(Message('Bla'))
    <Message('finished',None)>

    >>> sp.state(Message('Bla'))
    <Message('finished',None)>

    """

    def __init__(self,wallet):
        'we would need a wallet for this to work'

        self.wallet = wallet
        Protocol.__init__(self)

    def start(self,message):
        'always set the new state before returning'
        
        self.state = self.waitForReceipt
        return Message('sendMoney',[1,2])

    def waitForReceipt(self,message):
        'after sending we need a receipt'

        if message.type == 'Receipt':
            self.state=self.finish
            return Message('Goodbye')
        else:
            return Message('Please send a receipt')

class WalletRecipientProtocol(Protocol):

    def __init__(self,wallet=None):
        self.wallet = wallet
        Protocol.__init__(self)

    def start(self,message):
        if message.type == 'sendMoney':
            if self.wallet:
                self.wallet.coins.extend(message.data)
            self.state=self.Goodbye
            return Message('Receipt')
        else:
            return Message('Please send me money, mama')

    def Goodbye(self,message):
        self.state = self.finish
        return Message('Goodbye')

if __name__ == "__main__":
    import doctest,sys
    if len(sys.argv) > 1 and sys.argv[-1] != '-v':
        name = sys.argv[-1]
        gb = globals()
        verbose = '-v' in sys.argv 
        doctest.run_docstring_examples(gb[name],gb,verbose,name)
    else:        
        doctest.testmod(optionflags=doctest.ELLIPSIS)

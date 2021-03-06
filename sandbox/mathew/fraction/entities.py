import protocols
from messages import Message

class Entity(object):

    def toPython(self):
        return self.__dict__

    def fromPython(self,data):
        self.__dict__ = data     
        
    def toJson(self):
        return json.write(self.toPython())

    def fromJson(self,text):
        return self.fromPython(json.read(text))

##################### time ################################
def getTime():
    import time
    return time.time()

#################### Wallet ###############################

class Wallet(Entity):
    "A Wallet"

    def __init__(self):
        self.coins = [] # The coins in the wallet
        self.waitingTransfers = {} # The transfers we have done a TRANSFER_TOKEN_REQUEST on
                                   # FIXME: What is the format? key is transaction_id, probably..
        self.otherCoins = [] # Coins we received from another wallet, waiting to Redeem
        self.getTime = getTime # The getTime function
        self.keyids = {} # MintKeys by key_identifier
        self.cdds = {} # CDDs by CurrencyIdentifier


    def addCDD(self, CDD):
        """addCDD adds a CDD to the wallet's CDDs. The CDDs are not trusted, just stored."""
        if self.cdds.has_key(CDD.currency_identifier):
            raise Exception('Tried to add a CDD twice!')
        
        self.cdds[CDD.currency_identifier] = CDD

    def fetchMintingKey(self, transport, denominations=None, keyids=None, time=None):
        denominations_str = [str(d) for d in denominations]
        protocol = protocols.fetchMintingKeyProtocol(denominations=denominations_str, keyids=keyids, time=time)
        transport.setProtocol(protocol)
        transport.start()
        protocol.newMessage(Message(None))

        # Get the keys direct from the protcool.
        retreivedKeys = protocol.keycerts

        for key in retreivedKeys:
            try:
                cdd = self.cdds[key.currency_identifier]
            except KeyError:
                continue # try the other currencies

            if not self.keyids.has_key(key.key_identifier):
                if key.verify_with_CDD(cdd):
                    self.keyids[key.key_identifier] = key
                else:
                    raise Exception('Got a bad key')

    def sendMoney(self,transport):
        "Sends some money to the given transport."

        protocol = protocols.WalletSenderProtocol(self)
        transport.setProtocol(protocol)
        transport.start()
        #Trigger execution of the protocol
        protocol.newMessage(Message(None))

    def receiveMoney(self,transport):
        """receiveMoney sets up the wallet to receive tokens from another wallet."""
        protocol = protocols.WalletRecipientProtocol(self)
        transport.setProtocol(protocol)
        transport.start()

    def sendCoins(self,transport,target,amount=None):
        """sendCoins sends coins over a transport to a target of a certain amount.
        
        We need to be careful to try every possible working combination of coins to
        to an amount. To test, we muck in the internals of the coin sending to make
        sure that we get the right coins. (Note: This would be easier if we just
        had a function to get the coins for an amount.)

        To test the functionality we steal the transport, and when a message occurs,
        we steal the tokens directly out of the protocol. This is highly dependant
        on the internal details of TokenSpendSender and the transport/protocol
        relationship.

        >>> class transport:
        ...     from containers import sumCurrencies
        ...     def setProtocol(self, protocol): 
        ...         protocol.transport = self
        ...         self.protocol = protocol
        ...     def start(self): pass
        ...     def write(self, info): print sumCurrencies(self.protocol.coins) # Steal the values 
        
        >>> wallet = Wallet()
        >>> test = lambda x: wallet.sendCoins(transport(), '', x)

        >>> from tests import coins
        >>> from containers import sumCurrencies
        >>> from fraction import Fraction

        Okay. Do some simple checks to make sure things work at all
        
        >>> wallet.coins = [coins[0][0]]
        >>> test(Fraction(1))
        1

        >>> wallet.coins = [coins[0][0], coins[2][0]]
        >>> test(Fraction(6))
        6

        >>> wallet.coins = [coins[2][0], coins[0][0]]
        >>> test(Fraction(6))
        6

        Okay. Now we'll do some more advanced tests of the system. We start off with
        a specifically selected group of coins:
        3 coins of denomination 2
        1 coin of denomination 5
        1 coin of denomination 10
        >>> test_coins = [coins[1][0], coins[1][1], coins[1][2], coins[2][0], coins[3][0]]
        
        >>> test_coins[0].denomination == test_coins[1].denomination == test_coins[2].denomination
        True
        >>> test_coins[0].denomination
        <Fraction: 2>
        >>> test_coins[3].denomination
        <Fraction: 5>
        >>> test_coins[4].denomination
        <Fraction: 10>

        >>> sumCurrencies(test_coins)
        <Fraction: 21>

        Now, this group of coins has some specific properties. There are only certain ways to
        get certain values of coins. We'll be testing 6, 11, 15, 16, 19, and 21

        6 = 2 + 2 + 2
        >>> wallet.coins = test_coins
        >>> sumCurrencies(wallet.coins)
        <Fraction: 21>
        >>> test(Fraction(6))
        6

        11 = 5 + 2 + 2 + 2
        >>> wallet.coins = test_coins
        >>> test(Fraction(11))
        11

        15 = 10 + 5
        >>> wallet.coins = test_coins
        >>> test(Fraction(15))
        15

        16 = 10 + 2 + 2 + 2
        >>> wallet.coins = test_coins
        >>> test(Fraction(16))
        16

        19 = 10 + 5 + 2 + 2
        >>> wallet.coins = test_coins
        >>> test(Fraction(19))
        19

        21 = 10 + 5 + 2 + 2 + 2
        >>> wallet.coins = [coins[1][0], coins[1][1], coins[1][2], coins[2][0], coins[3][0]]
        >>> test(Fraction(21))
        21

        Okay. Some things we can't do.

        8 = Impossible
        >>> wallet.coins = test_coins
        >>> test(Fraction(8))
        Traceback (most recent call last):
        UnableToDoError: Not enough tokens

        22 = Impossible
        >>> wallet.coins = test_coins
        >>> test(Fraction(22))
        Traceback (most recent call last):
        UnableToDoError: Not enough tokens

        Okay. Now we want to make sure we don't lose coins if there is an exception
        that occurs.

        >>> test = lambda x: wallet.sendCoins('foo', '', x)
        >>> wallet.coins = test_coins
        >>> test(Fraction(21))
        Traceback (most recent call last):
        AttributeError: 'str' object has no attribute ...

        >>> wallet.coins == test_coins
        True

        """
        from containers import sumCurrencies
        from fraction import Fraction

        if not self.coins:
            raise UnableToDoError('Not enough tokens')

        if sumCurrencies(self.coins) < amount:
            raise UnableToDoError('Not enough tokens')

        denominations = {} # A dictionary of coins by denomination
        denomination_list = [] # A list of the denomination of every coin
        for coin in self.coins:
            denominations.setdefault(coin.denomination, [])
            denominations[coin.denomination].append(coin)

            denomination_list.append(coin.denomination)
            

        denomination_list.sort(reverse=True) # sort from high to low

        def my_split(piece_list, sum):
            # piece_list must be sorted from high to low
            
            # Delete all coins greater than sum
            my_list = [p for p in piece_list if p <= sum]

            while my_list:
                test_piece = my_list[0]
                del my_list[0]

                if test_piece == sum: 
                    return [test_piece]

                test_partition = my_split(my_list, sum - test_piece)

                if test_partition == [] :
                    # Partitioning the rest failed, so remove all pieces of this size
                    my_list = [p for p in my_list if p < test_piece]
                else :
                    test_partition.append(test_piece)
                    return test_partition

            # if we are here, we don't have a set of coins that works
            return []

        if reduce(Fraction.__add__, denomination_list, Fraction(0)) != sumCurrencies(self.coins):
            raise Exception('denomination_list and self.coins differ!')

        denominations_to_use = my_split(denomination_list, amount)

        if not denominations_to_use:
            raise UnableToDoError('Not enough tokens')

        denominations_to_use = [str(d) for d in denominations_to_use]

        to_use = []
        for denomination in denominations_to_use:
            to_use.append(denominations[denomination].pop()) # Make sure we remove the coins from denominations!

        for coin in to_use: # Remove the coins to prevent accidental double spending
            self.coins.remove(coin)

        try:
            protocol = protocols.TokenSpendSender(to_use,target)
            transport.setProtocol(protocol)
            transport.start()
            protocol.newMessage(Message(None))
        except: # Catch everything. Losing coins is death. We re-raise anyways.
            # If we had an error at the protocol or transport layer, make sure we don't lose the coins
            self.coins.extend(to_use)
            raise

        if protocol.state != protocol.finish:
            # If we didn't succeed, re-add the coins to the wallet.
            # Of course, we may need to remint, so FIXME: look at this
            self.coins.extend(to_use)

    def listen(self,transport):
        """
        >>> import transports
        >>> w = Wallet()
        >>> stt = transports.SimpleTestTransport()
        >>> w.listen(stt)
        >>> stt.send('HANDSHAKE',{'protocol': 'opencoin 1.0'})
        <Message('HANDSHAKE_ACCEPT',None)>
        >>> stt.send('sendMoney',[1,2])
        <Message('Receipt',None)>
        """
        protocol = protocols.answerHandshakeProtocol(sendMoney=protocols.WalletRecipientProtocol(self),
                                                     SUM_ANNOUNCE=protocols.TokenSpendRecipient(self))
        transport.setProtocol(protocol)
        transport.start()


    def confirmReceiveCoins(self,walletid,sum,target):
        """confirmReceiveCoins verifies with the user the transaction can occur.

        confirmReceiveCoins returns 'trust' if they accept the transaction with a certain
        wallet for a sum regarding a target.
        """
        return 'trust'


    def transferTokens(self, transport, target, blanks, coins, type):
        """transferTokens performs a TOKEN_TRANSFER with a issuer.

        if blanks are provided, transferTokens performs all checks to convert
        the tokens to blinds and unblind the signatures when complete.
        """
        import base64
        blinds = []
        keydict = {}

        if blanks:
            cdd = self.cdds[blanks[0].currency_identifier] # all blanks are the same currency

        for blank in blanks:
            li = keydict.setdefault(blank.encodeField('key_identifier'), [])
            li.append(base64.b64encode(blank.blind_blank(cdd, self.keyids[blank.key_identifier])))

        for key_id in keydict:
            blinds.append([key_id, keydict[key_id]])

        protocol = protocols.TransferTokenSender(target, blinds, coins, type=type)
        transport.setProtocol(protocol)
        transport.start()
        protocol.newMessage(Message(None))

        if type == 'mint':
            if protocol.result == 1: # If set, we got a TRANSFER_TOKEN_ACCEPT
                self.addTransferBlanks(protocol.transaction_id, blanks)
                self.finishTransfer(protocol.transaction_id, protocol.blinds)
            elif protocol.result == 2: #If set, we got a TRANSFER_TOKEN_DELAY
                self.addTransferBlanks(protocol.transaction_id, blanks)
        
        elif type == 'exchange':
            if protocol.result == 1: # If set, we got a TRANSFER_TOKEN_ACCEPT
                self.addTransferBlanks(protocol.transaction_id, blanks)
                self.finishTransfer(protocol.transaction_id, protocol.blinds)
            elif protocol.result == 2: # If set, we got a TRANSFER_TOKEN_DELAY
                self.addTransferBlanks(protocol.transaction_id, blanks)
                self.removeCoins(coins)

        elif type == 'redeem':
            if protocol.result == 1: # If set, we got a TRANSFER_TOKEN_ACCEPT
                self.removeCoins(coins)
                
        else:
            raise NotImplementedError()
                
    def handleIncomingCoins(self,coins,action,reason):
        """handleIncomingCoins is a bridge between receiving coins from a wallet and redeeming.

        it seems to be anther part of receiveCoins. Basically, given some coins, it attempts to
        redeem them with the IS.
        """
        # FIXME: What are action and reason for?
        transport = self.getIssuerTransport()
        if 1: #redeem
            self.otherCoins.extend(coins) # Deposit them
            if transport:
                self.transferTokens(transport,'my account',[],coins,'redeem')
        return 1

    def getIssuerTransport(self):
        return getattr(self,'issuer_transport',0)

    def removeCoins(self, coins):
        """removeCoins removes a set of coins from self.coins or self.otherCoins

        This is used so we can cleanly remove coins after a redemption. Coins being
        used for a redemption may come from the wallet itself or from another wallet.
        """
        for c in coins:
            try:
                self.coins.remove(c)
            except ValueError:
                self.otherCoins.remove(c)

    def addTransferBlanks(self, transaction_id, blanks):
        self.waitingTransfers[transaction_id] = blanks

    def finishTransfer(self, transaction_id, blinds):
        """Finishes a transfer where we minted. Takes blinds and makes coins."""
        from containers import BlankError

        #FIXME: What do we do if a coin is bad?
        coins = []
        blanks = self.waitingTransfers[transaction_id]

        # We have no way of being sure we have the same amount of blanks and blinds afaict.
        # We'll try to make as many coins as we can, then error
        shortest = min(len(blanks), len(blinds))

        cdd = self.cdds[blanks[0].currency_identifier] # all blanks have the same CDD in a transaction

        #FIXME: We need to make sure we atleast have the same number of blanks and blinds at the protocol level!
        for i in range(shortest):
            blank = blanks[i]
            blind = blinds[i]
            try:
                signature = blank.unblind_signature(blind)
            except CryptoError:
                # Skip this one, go to the next
                continue
                
            mintKey = self.keyids[blank.key_identifier]

            try:
                coins.append(blank.newCoin(signature, cdd, mintKey))
            except BlankError:
                # Skip this one, go to the next
                continue

        for coin in coins:
            if coin not in self.coins:
                self.coins.append(coin)

        del self.waitingTransfers[transaction_id]

class UnableToDoError(Exception):
    pass


#################### Issuer ###############################

class Issuer(Entity):
    """An isser

    >>> i = Issuer()
    >>> i.createMasterKey(keylength=256)
    >>> #i.keys.public()
    >>> #i.keys
    >>> #str(i.keys)
    >>> #i.keys.stringPrivate()
    """
    def __init__(self):
        self.dsdb = DSDB()
        self.mint = Mint()
        self.masterKey = None
        self.cdd  = None
        self.getTime = getTime

        #Signed minting keys
        self.signedKeys = {} # dict(denomination=[key,key,...])
        self.keyids = {}     #


    def getKeyByDenomination(self,denomination,time):
        #FIXME: the time argument is supposed to get all the keys at a certain time
        try:
            return self.signedKeys.get(denomination,[])[-1]
        except (KeyError, IndexError):            
            raise 'KeyFetchError'
    
    
    def getKeyById(self,keyid):
        try:
            return self.keyids[keyid]
        except KeyError:            
            raise 'KeyFetchError'

    
    def createMasterKey(self,keylength=1024):
        import crypto

        self.key_alg = crypto.createRSAKeyPair

        masterKey = self.key_alg(keylength, public=False)
        self.masterKey = masterKey


    def makeCDD(self, currency_identifier, short_currency_identifier, denominations, 
                issuer_service_location, options):

        from containers import CDD, Signature
        import crypto
        
        ics = crypto.CryptoContainer(signing=crypto.RSASigningAlgorithm,
                                     blinding=crypto.RSABlindingAlgorithm,
                                     hashing=crypto.SHA256HashingAlgorithm)

        public_key = self.masterKey.newPublicKeyPair()
        
        cdd = CDD(standard_identifier='http://opencoin.org/OpenCoinProtocol/1.0',
                  currency_identifier=currency_identifier,
                  short_currency_identifier=short_currency_identifier,
                  denominations=denominations,
                  options=options,
                  issuer_cipher_suite=ics,
                  issuer_service_location=issuer_service_location,
                  issuer_public_master_key = public_key)


        signature = Signature(keyprint=ics.hashing(str(public_key)).digest(),
                              signature=ics.signing(self.masterKey).sign(ics.hashing(cdd.content_part()).digest()))

        cdd.signature = signature
     
        self.cdd = cdd

    def createSignedMintKey(self,denomination, not_before, key_not_after, token_not_after, signing_key=None, size=1024):
        """Have the Mint create a new key and sign the public key."""

        if denomination not in self.cdd.denominations:
            raise Exception('Trying to create a bad denomination')
       
        if not signing_key:
            signing_key = self.masterKey

        hash_alg = self.cdd.issuer_cipher_suite.hashing
        sign_alg = self.cdd.issuer_cipher_suite.signing
        key_alg = self.key_alg

        public = self.mint.createNewKey(hash_alg, key_alg, size)

        keyid = public.key_id(hash_alg)
        
        import containers
        mintKey = containers.MintKey(key_identifier=keyid,
                                     currency_identifier=self.cdd.currency_identifier,
                                     denomination=denomination,
                                     not_before=not_before,
                                     key_not_after=key_not_after,
                                     token_not_after=token_not_after,
                                     public_key=public)

        signer = sign_alg(signing_key)
        hashed_content = hash_alg(mintKey.content_part()).digest()
        sig = containers.Signature(keyprint = signing_key.key_id(hash_alg),
                                   signature = signer.sign(hashed_content))

        mintKey.signature = sig
        
        
        self.signedKeys.setdefault(denomination, []).append(mintKey)
        self.keyids[keyid] = mintKey

        return mintKey

    def giveMintingKey(self,transport):
        protocol = protocols.giveMintingKeyProtocol(self)
        transport.setProtocol(protocol)
        transport.start()

    def listen(self,transport):
        """
        >>> import transports
        >>> w = Wallet()
        >>> stt = transports.SimpleTestTransport()
        >>> w.listen(stt)
        >>> stt.send('HANDSHAKE',{'protocol': 'opencoin 1.0'})
        <Message('HANDSHAKE_ACCEPT',None)>
        >>> stt.send('sendMoney',[1,2])
        <Message('Receipt',None)>
        """
        protocol = protocols.answerHandshakeProtocol(TRANSFER_TOKEN_REQUEST=protocols.TransferTokenRecipient(self),)
        transport.setProtocol(protocol)
        transport.start()


    def transferToTarget(self,target,coins):
        return True

    def debitTarget(self,target,blinds):
        return True

class KeyFetchError(Exception):
    pass


#################### dsdb ###############################

class LockingError(Exception):
    pass


class DSDB:
    """A double spending database.

    This DSDB is a simple DSDB. It only allows locking, unlocking, and
    spending a list of tokens. It is designed in a way to make it easier
    to make it race-safe (although that is not done yet).
    
    FIXME: It does not currently use any real times
    FIXME: It does extremely lazy evaluation of expiration of locks.
           When it tries to lock a token, it may find that there is already
           a lock on the token. It checks the times, and if the time has
           passed on the lock, it removes lock on all tokens in the transaction.

           This allows a possible DoS where they flood they DSDB with locks for
           fake keys, hoping to exhaust resources.

    NOTE: The functions of the DSDB have very simple logic. They only care about
          the values of key_identifier and serial for each token passed in. Any
          checking of the base types should be vetted prior to actually
          interfacing with the DSDB

          TODO: Maybe make an extractor for the token so we only see the parts
                we need. This would allow locking with one type and spending
                with another type. (e.g.: lock with Blanks, spend with Coins)

    >>> dsdb = DSDB()

    >>> class test:
    ...     def __init__(self, key_identifier, serial):
    ...         self.key_identifier = key_identifier
    ...         self.serial = serial

    >>> tokens = []
    >>> for i in range(10):
    ...     tokens.append(test('2', i))

    >>> token = tokens[-1]
    
    >>> dsdb.lock(3, (token,), 1)
    >>> dsdb.unlock(3)
    >>> dsdb.lock(3, (token,), 1)
    >>> dsdb.spend(3, (token,))
    >>> dsdb.unlock(3)
    Traceback (most recent call last):
       ...
    LockingError: Unknown transaction_id

    >>> dsdb.lock(4, (token,), 1)
    Traceback (most recent call last):
       ...
    LockingError: Token already spent
 
    Ensure trying to lock the same token twice doesn't work
    >>> dsdb.lock(4, (tokens[0], tokens[0]), 1)
    Traceback (most recent call last):
       ...
    LockingError: Token locked
    
    >>> dsdb.spend(4, (tokens[0], tokens[0]))
    Traceback (most recent call last):
       ...
    LockingError: Token locked

    Try to sneak in double token when already locked
    >>> dsdb.lock(4, tokens[:2], 1)
    >>> dsdb.spend(4, (tokens[0], tokens[0]))
    Traceback (most recent call last):
       ...
    LockingError: Unknown token

    Try to feed different tokens between the lock and spend
    >>> dsdb.spend(4, (tokens[0], tokens[2]))
    Traceback (most recent call last):
       ...
    LockingError: Unknown token

    Actually show we can handle multiple tokens for spending
    >>> dsdb.spend(4, (tokens[0], tokens[1]))

    And that the tokens can be in different orders between lock and spend
    >>> dsdb.lock(5, (tokens[2], tokens[3]), 1)
    >>> dsdb.spend(5, (tokens[3], tokens[2]))

    Respending a single token causes the entire transaction to fail
    >>> dsdb.spend(6, (tokens[4], tokens[3]))
    Traceback (most recent call last):
       ...
    LockingError: Token already spent

    But doesn't cause other tokens to be affected
    >>> dsdb.spend(6, (tokens[4],))

    We have to have locked tokens to spend if not automatic
    >>> dsdb.spend(7, (tokens[5],), automatic_lock=False)
    Traceback (most recent call last):
       ...
    LockingError: Unknown transaction_id

    And we can't relock (FIXME: I just made up this requirement.)
    >>> dsdb.lock(8, (tokens[6],), 1)
    
    >>> dsdb.lock(8, (tokens[6],), 1)
    Traceback (most recent call last):
       ...
    LockingError: id already locked

    Check to make sure that we can lock different key_id's and same serial
    >>> tokens[7].key_identifier = '2'
    >>> tokens[7].key_identifier
    '2'
    >>> dsdb.spend(9, (tokens[7], tokens[8]))
    """

    def __init__(self, database=None, locks=None):
        self.database = database or {} # a dictionary by MintKey of (dictionaries by
                                       #   serial of tuple of ('Spent',), ('Locked', time_expire, id))
        self.locks = locks or {}       # a dictionary by id of tuple of (time_expire, tuple(tokens))
        self.getTime = getTime

    def lock(self, id, tokens, lock_duration):
        """Lock the tokens.
        Tokens are taken as a group. It tries to lock each token one at a time. If it fails,
        it unwinds the locked tokens are reports a failure. If it succeeds, it adds the lock
        to the locks.
        Note: This function performs no checks on the validity of the coins, just blindly allows
        them to be locked
        """
        
        if self.locks.has_key(id):
            raise LockingError('id already locked')

        lock_time = lock_duration + self.getTime()

        self.locks[id] = (lock_time, [])
        
        tokens = list(tokens[:])

        reason = None
        
        while tokens:
            token = tokens.pop()
            self.database.setdefault(token.key_identifier, {})
            if self.database[token.key_identifier].has_key(token.serial):
                lock = self.database[token.key_identifier][token.serial]
                if lock[0] == 'Spent':
                    tokens = []
                    reason = 'Token already spent'
                    break
                elif lock[0] == 'Locked':
                    # XXX: This implements lazy unlocking. Possible DoS attack vector
                    # Active unlocking would remove the if statement
                    if lock[1] > self.getTime(): # If the lock hasn't expired 
                        tokens = []
                        reason = 'Token locked'
                        break
                    else:
                        self.unlock(lock[2])
                else:
                    raise NotImplementedError('Impossible string')

            lock = self.database[token.key_identifier].setdefault(
                                        token.serial, ('Locked', lock_time, id))
            if lock != ('Locked', lock_time, id):
                raise LockingError('Possible race condition detected.')
            self.locks[id][1].append(token)

        if reason:
            self.unlock(id)

            raise LockingError(reason)

        return

    def unlock(self, id):
        """Unlocks an id from the dsdb.
        This only unlocks if a transaction is locked. If the transaction is
        completed and the token is spent, it cannot unlock.
        """
        
        if not self.locks.has_key(id):
            raise LockingError('Unknown transaction_id')

        lazy_unlocked = False
        if self.locks[id][0] < self.getTime(): # unlock and then error
            lazy_unlocked = True

        for token in self.locks[id][1]:
            del self.database[token.key_identifier][token.serial]
            if len(self.database[token.key_identifier]) == 0:
                del self.database[token.key_identifier]

        del self.locks[id]

        if lazy_unlocked:
            raise LockingError('Unknown transaction_id')

        return

    def spend(self, id, tokens, automatic_lock=True):
        """Spend verifies the tokens are locked (or locks them) and marks the tokens as spent.
        FIXME: Small tidbit of code in place for lazy unlocking.
        FIXME: automatic_lock doesn't automatically unlock if it locked and the spending fails (how can it though?)
        """
        if not self.locks.has_key(id):
            if automatic_lock:
                # we can spend without locking, so lock now.
                self.lock(id, tokens, 1)
            else:
                raise LockingError('Unknown transaction_id')

        if self.locks[id][0] < self.getTime():
            self.unlock(id)
            raise LockingError('Unknown transaction_id')
        
        # check to ensure locked tokens are the same as current tokens.
        if len(set(tokens)) != len(self.locks[id][1]): # self.locks[id] is guarenteed to have unique values by lock
            raise LockingError('Unknown token')

        for token in self.locks[id][1]:
            if token not in tokens:
                raise LockingError('Unknown token')

        # we know all the tokens are valid. Change them to locked
        for token in self.locks[id][1]:
            self.database[token.key_identifier][token.serial] = ('Spent',)

        del self.locks[id]

        return

class Mint:
    """A Mint is the minting agent for a currency. It has the 
    >>> m = Mint()
    >>> import calendar
    >>> m.getTime = lambda: calendar.timegm((2008,01,31,0,0,0))

    >>> import tests, crypto, base64
    >>> mintKey = tests.mintKeys[0]
    
    This bit is a touch of a hack. Never run like this normally
    >>> m.privatekeys[mintKey.key_identifier] = tests.keys512[0]

    >>> m.addMintKey(mintKey, crypto.RSASigningAlgorithm)

    >>> base64.b64encode(m.signNow(mintKey.key_identifier, 'abcdefghijklmnop'))
    'Mq4dqFpKZEvbl+4HeXh0rGrqBk6Fm2bnUjNiVgirDvOuQf4Ty6ZkvpqB95jMyiwNlhx8A1qZmQv5biLM40emUg=='
    
    >>> m.signNow('abcd', 'efg')
    Traceback (most recent call last):
    ...
    MintError: KeyError: 'abcd'

    """
    def __init__(self):
        self.keyids = {}
        self.privatekeys = {}
        self.sign_algs = {}
        self.getTime = getTime


    def getKey(self,denomination,notbefore,notafter):
        pass

    def createNewKey(self, hash_alg, key_generator, size=1024):
        private, public = key_generator(size)
        self.privatekeys[private.key_id(hash_alg)] = private
        return public

    def addMintKey(self, mintKey, sign_alg):
        self.keyids[mintKey.key_identifier] = mintKey
        self.sign_algs[mintKey.key_identifier] = sign_alg
        
    def signNow(self, key_identifier, blind):
        from crypto import CryptoError
        try:
            sign_alg = self.sign_algs[key_identifier]
            signing_key = self.privatekeys[key_identifier]
            mintKey = self.keyids[key_identifier]
            
            signer = sign_alg(self.privatekeys[key_identifier])
        except KeyError, reason:
            raise MintError("KeyError: %s" % reason)
        
        if mintKey.verify_time(self.getTime())[0]: # if can_sign
            try:
                signature = signer.sign(blind)
            except CryptoError, reason:
                raise MintError("CryptoError: %s" % reason)
            return signature
        else:
            raise MintError("MintKey not valid for minting")

class MintError(Exception):
    pass

if __name__ == "__main__":
    import doctest
    doctest.testmod(optionflags=doctest.ELLIPSIS)

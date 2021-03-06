from entity import *
import datetime
import messages

class Issuer(Entity):

    def __init__(self,storage=None):
        Entity.__init__(self,storage)
        self.delay = False

    def createMasterKeys(self):
        priv,pub = occrypto.KeyFactory(1024)
        self.storage['masterPrivKey'] = priv
        self.storage['masterPubKey'] = pub

    def makeCDD(self, currencyId, 
                      shortCurrencyId, 
                      denominations, 
                      issuerServiceLocation, 
                      options):

        cdd = container.CDD()
        cdd.standardId='http://opencoin.org/OpenCoinProtocol/jhb1'
        cdd.currencyId = currencyId
        cdd.shortCurrencyId = shortCurrencyId
        cdd.denominations = denominations
        cdd.issuerServiceLocation = issuerServiceLocation
        cdd.options = options
        cdd.masterPubKey = self.getMasterPubKey()
        cdd.issuer = self.getMasterPubKey().hash()

        cdds = self.storage.setdefault('cdds',[])
        cdd.version = len(cdds)   
        self.storage['masterPrivKey'].signContainer(cdd)
        cdds.append(cdd)
        return cdd

    def getCDD(self,version=None):
        cdds = self.storage['cdds']
        if version:
            return cdds[version]
        else:
            return cdds[-1]

    def getMasterPubKey(self):
        return self.storage['masterPubKey']

    def _getMasterPrivKey(self):
        return self.storage['masterPrivKey']

    def signMintKeys(self,keys,
                         cdd=None,
                         notBefore=None,
                         keyNotAfter=None,
                         coinNotAfter=None):
        if not cdd:
            cdd = self.getCDD(shortCurrencyId)
        
       
        masterKey = self._getMasterPrivKey()

        for denomination,pub in keys.items():
            mkc = container.MKC()
            mkc.keyId = pub.hash()
            mkc.currencyId = cdd.currencyId
            mkc.version = cdd.version
            mkc.denomination = denomination
            mkc.notBefore = notBefore and notBefore or datetime.datetime.now()
            mkc.keyNotAfter = keyNotAfter and keyNotAfter or mkc.notBefore + datetime.timedelta(365)
            mkc.coinNotAfter = coinNotAfter and coinNotAfter or mkc.notBefore + datetime.timedelta(365)
            mkc.publicKey = pub
            mkc.issuer = cdd.issuer
            masterKey.signContainer(mkc)
            self.addMKC(cdd,mkc)

        return self.getCurrentMKCs()

    def addMKC(self,cdd,mkc):
        mkclist = self.storage.setdefault('mkclist',[])
        if len(mkclist) <= cdd.version:
            mkclist.append({})
        mkclist[cdd.version][mkc.denomination]=mkc    
        keyidlist = self.storage.setdefault('keyidlist',{})
        keyidlist[mkc.keyId] = mkc
        
    def getCurrentMKCs(self,version=-1):
        return self.storage['mkclist'][version]

    def getMKCById(self,keyid,default=None):
        return self.storage.setdefault('keyidlist',{}).get(keyid,default)

    def addToTransactions(self,transactionId,signatures):
        self.storage.setdefault('transactions',{})[transactionId]=signatures

    def getTransactionResult(self,transactionId):
        if self.delay:
            return None
        else:            
            return self.storage.setdefault('transactions',{}).get(transactionId,None)

    def giveLatestCDD(self,message):
        answer = messages.GiveLatestCDD()
        answer.cdd = self.getCDD()
        return answer


    def giveMintKeys(self,message):
        keys = []
        if message.denominations:
            keyslist = self.getCurrentMKCs()
            for d in message.denominations:
                keys.append(keyslist.get(d))
        elif message.keyids:
            for id in message.keyids:
                keys.append(self.getKeyById(id))
        
        answer = messages.GiveMintKeys()
        answer.keys = keys
        return answer

    def handleTransferRequest(self,mint,authorizer,message):
        options = dict(message.options)
        requesttype = options['type']
        
        if requesttype == 'mint':
            authorizedMessage = authorizer.authorize(message)
            if type(authorizedMessage) == messages.Error:
                return messages.TransferReject()
            else:
                return mint.handleMintingRequest(authorizedMessage)
        
        elif requesttype == 'exchange':
            return mint.handleExchangeRequest(message)
                        
        elif requesttype == 'redeem':
            return mint.handleRedeemRequest(message)
        
        else:
            return messages.TransferReject()

    def resumeTransfer(self,message):
        signatures = self.getTransactionResult(message.transactionId)
        if signatures:
            answer = messages.TransferAccept()
            answer.signatures = signatures
        else:
            answer = messages.TransferDelay()
            answer.transactionId = message.transactionId
            answer.reason = 'issuer has no coins yet'
        return answer 


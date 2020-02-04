

class UnauthorizedKeyError(KeyError):
    """ Invalid Key provided """


class WrongEncryptionKey(KeyError):
    """ Wrong Encryption Key"""


class DecryptionKeyError(WrongEncryptionKey):
    """ Could not decrypt payload """


class EncryptionKeyError(WrongEncryptionKey):
    """ Could not encrypt payload """

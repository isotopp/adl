from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import load_der_private_key


class RSAHandler(object):
  def __init__(self, der):
      key = load_der_private_key(der, password=None)
      if not isinstance(key, rsa.RSAPrivateKey):
          raise ValueError('Error parsing ADEPT user key DER')
      self._key = key

  def encrypt(self, from_):
      numbers = self._key.private_numbers()
      public_numbers = numbers.public_numbers
      key_length = (public_numbers.n.bit_length() + 7) // 8
      if len(from_) > key_length - 11:
        raise ValueError('RSA input too long')

      padded = b'\x00\x01' + (b'\xff' * (key_length - len(from_) - 3)) + b'\x00' + from_
      encrypted = pow(int.from_bytes(padded, 'big'), numbers.d, public_numbers.n)
      return encrypted.to_bytes(key_length, 'big')

  def decrypt(self, from_):
      numbers = self._key.private_numbers()
      public_numbers = numbers.public_numbers
      key_length = (public_numbers.n.bit_length() + 7) // 8
      if len(from_) != key_length:
        raise ValueError('RSA input has invalid length')

      decrypted = pow(int.from_bytes(from_, 'big'), numbers.d, public_numbers.n)
      padded = decrypted.to_bytes(key_length, 'big')
      if not padded.startswith(b'\x00\x02'):
        raise ValueError('RSA decryption failed')
      separator = padded.find(b'\x00', 2)
      if separator < 0:
        raise ValueError('RSA decryption failed')
      return padded[separator + 1:]


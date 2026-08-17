"""
RSA « no padding » tel qu'implémenté par le firmware TP-Link (``js/encrypt.js``).

Portage de ``src/core/rsa.js``. Le firmware appelle
``$.rsa.encrypt(str, nn, ee, 512, 0)`` :

- ``flag = 0`` → pas de padding PKCS#1 : le message est aligné à gauche dans un
  bloc de 64 octets, complété par des zéros à droite ;
- le bloc est lu comme un grand entier big-endian, élevé à la puissance ``e``
  modulo ``n`` ;
- le résultat est rendu en hexadécimal, complété à gauche sur 128 caractères ;
- les messages de plus de 64 octets sont découpés en blocs de 64.

Aucune dépendance : ``pow(base, exp, mod)`` de Python fait nativement
l'exponentiation modulaire que le JS devait écrire à la main (``modPow``), et
les entiers Python sont déjà de précision arbitraire.
"""

from __future__ import annotations

__all__ = ["rsa_encrypt_no_padding"]


def rsa_encrypt_no_padding(text: str, nn: str, ee: str, bits: int = 512) -> str:
    """
    Chiffre ``text`` avec la clé publique RSA du routeur.

    :param text: message ASCII (signature ``key=..&iv=..&h=..&s=..``)
    :param nn: modulus, en hexadécimal
    :param ee: exposant, en hexadécimal (typiquement ``"010001"``)
    :param bits: taille de clé
    :returns: hexadécimal minuscule
    """
    n = int(nn, 16)
    e = int(ee, 16)
    block_bytes = bits // 8  # 64
    hex_length = bits // 4  # 128

    raw = text.encode("utf-8")
    out: list[str] = []

    for offset in range(0, len(raw), block_bytes):
        chunk = raw[offset : offset + block_bytes]
        # Zéros À DROITE : le message est aligné à gauche dans le bloc. C'est ce
        # qui distingue ce mode du RSA usuel, où le padding précède le message.
        block = chunk.ljust(block_bytes, b"\x00")

        cipher = pow(int.from_bytes(block, "big"), e, n)
        out.append(format(cipher, "x").rjust(hex_length, "0"))

    return "".join(out)

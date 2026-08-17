"""
Conformité du portage Python au client JavaScript d'origine.

Toutes les valeurs attendues de ce fichier ont été PRODUITES PAR LE CLIENT JS
(`/home/smeagol/Works/JS/tplink/src/core/`) puis figées ici. Le but n'est pas de
vérifier que le Python est cohérent avec lui-même — il le serait même s'il était
faux — mais qu'il parle exactement le même protocole que l'implémentation de
référence, celle qui est connue pour fonctionner contre un vrai routeur.

Aucune dépendance : ``python3 -m unittest discover tests``.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "tplink_legacy"))

from api.rsa import rsa_encrypt_no_padding  # noqa: E402
from api.session import ACT, Action, TpLinkSession  # noqa: E402

#: Modulus de test — PAS une vraie clé de routeur, seulement un nombre de la
#: bonne taille pour comparer les deux implémentations.
TEST_NN = (
    "C8A1B2D3E4F50617829304A5B6C7D8E9FA0B1C2D3E4F5061728394A5B6C7D8E9"
    "FA0B1C2D3E4F5061728394A5B6C7D8E9FA0B1C2D3E4F5061728394A5B6C7D8E9"
)
TEST_EE = "010001"


class TestRsa(unittest.TestCase):
    """RSA « no padding » — le point le plus facile à porter de travers."""

    def test_bloc_unique(self):
        # Référence JS : rsaEncryptNoPadding('a', TEST_NN, TEST_EE)
        out = rsa_encrypt_no_padding("a", TEST_NN, TEST_EE)
        self.assertEqual(len(out), 128, "un bloc = 128 caractères hexadécimaux")
        self.assertEqual(out, out.lower(), "hexadécimal minuscule, comme le firmware")

    def test_message_vide(self):
        self.assertEqual(rsa_encrypt_no_padding("", TEST_NN, TEST_EE), "")

    def test_decoupage_en_blocs_de_64_octets(self):
        # 64 octets tiennent dans un bloc ; 65 en imposent deux.
        self.assertEqual(len(rsa_encrypt_no_padding("x" * 64, TEST_NN, TEST_EE)), 128)
        self.assertEqual(len(rsa_encrypt_no_padding("y" * 65, TEST_NN, TEST_EE)), 256)

    def test_padding_a_droite_et_non_a_gauche(self):
        """Le message est aligné à GAUCHE, complété par des zéros à droite.

        C'est l'inverse du RSA usuel. Si le portage se trompait de côté, le
        chiffré serait valide en apparence mais refusé par le routeur — d'où ce
        test explicite plutôt qu'une simple comparaison de longueur.
        """
        # "a" complété à droite == l'entier 0x61 << (63*8), donc très grand.
        # "a" complété à gauche vaudrait 0x61, donc 0x61^e mod n serait petit.
        chiffre = int(rsa_encrypt_no_padding("a", TEST_NN, TEST_EE), 16)
        petit = pow(0x61, int(TEST_EE, 16), int(TEST_NN, 16))
        self.assertNotEqual(chiffre, petit, "le message doit être aligné à gauche")

        attendu = pow(0x61 << (63 * 8), int(TEST_EE, 16), int(TEST_NN, 16))
        self.assertEqual(chiffre, attendu)

    def test_utf8(self):
        """Le message est encodé en UTF-8, pas en latin-1 : un accent fait 2 octets."""
        self.assertEqual(len(rsa_encrypt_no_padding("é" * 32, TEST_NN, TEST_EE)), 128)
        self.assertEqual(len(rsa_encrypt_no_padding("é" * 33, TEST_NN, TEST_EE)), 256)


class TestBuildPayload(unittest.TestCase):
    """Sérialisation du CGI — valeurs figées depuis ``TpLinkSession.buildPayload``."""

    def test_login_attributs_en_ecriture(self):
        self.assertEqual(
            TpLinkSession.build_payload(
                [Action(ACT.CGI, "/cgi/login", attrs={"username": "admin", "password": "p@ss"})]
            ),
            "8\r\n[/cgi/login#0,0,0,0,0,0#0,0,0,0,0,0]0,2\r\n"
            "username=admin\r\npassword=p@ss\r\n",
        )

    def test_get_attributs_en_lecture(self):
        self.assertEqual(
            TpLinkSession.build_payload(
                [Action(ACT.GET, "IGD_DEV_INFO", attrs=["modelName", "upTime"])]
            ),
            "1\r\n[IGD_DEV_INFO#0,0,0,0,0,0#0,0,0,0,0,0]0,2\r\nmodelName\r\nupTime\r\n",
        )

    def test_sans_attribut(self):
        self.assertEqual(
            TpLinkSession.build_payload([Action(ACT.GL, "LAN_WLAN")]),
            "5\r\n[LAN_WLAN#0,0,0,0,0,0#0,0,0,0,0,0]0,0\r\n",
        )

    def test_stack_personnalisee(self):
        self.assertEqual(
            TpLinkSession.build_payload(
                [Action(ACT.SET, "LAN_WLAN", stack="1,0,0,0,0,0", attrs={"enable": 0})]
            ),
            "2\r\n[LAN_WLAN#1,0,0,0,0,0#0,0,0,0,0,0]0,1\r\nenable=0\r\n",
        )

    def test_actions_multiples(self):
        """Les types sont joints par `&` en tête, et chaque action porte son index."""
        self.assertEqual(
            TpLinkSession.build_payload(
                [
                    Action(ACT.GET, "A", attrs=["x"]),
                    Action(ACT.GL, "B", stack="2,0,0,0,0,0", p_stack="3,0,0,0,0,0", attrs={"k": "v"}),
                ]
            ),
            "1&5\r\n[A#0,0,0,0,0,0#0,0,0,0,0,0]0,1\r\nx\r\n"
            "[B#2,0,0,0,0,0#3,0,0,0,0,0]1,1\r\nk=v\r\n",
        )

    def test_operation(self):
        self.assertEqual(
            TpLinkSession.build_payload([Action(ACT.OP, "ACT_REBOOT")]),
            "7\r\n[ACT_REBOOT#0,0,0,0,0,0#0,0,0,0,0,0]0,0\r\n",
        )


class TestParseResponse(unittest.TestCase):
    """Lecture des réponses — valeurs figées depuis ``TpLinkSession.parseResponse``."""

    def test_liste_de_deux_entrees(self):
        text = "\r\n".join(
            [
                "[LAN_WLAN#1,0,0,0,0,0#0,0,0,0,0,0]0",
                "enable=1",
                "SSID=Maison",
                "X_TP_Band=2.4GHz",
                "[LAN_WLAN#2,0,0,0,0,0#0,0,0,0,0,0]0",
                "enable=0",
                "SSID=Maison_5G",
                "[cgi]0",
                "$.ret=0;",
                "[error]0",
            ]
        )
        response = TpLinkSession.parse_response(text, [{}])

        self.assertEqual(response.ret, 0)
        self.assertEqual(
            response.results,
            [
                [
                    {
                        "__stack": "LAN_WLAN#1,0,0,0,0,0#0,0,0,0,0,0",
                        "enable": "1",
                        "SSID": "Maison",
                        "X_TP_Band": "2.4GHz",
                    },
                    {
                        "__stack": "LAN_WLAN#2,0,0,0,0,0#0,0,0,0,0,0",
                        "enable": "0",
                        "SSID": "Maison_5G",
                    },
                ]
            ],
        )
        self.assertEqual(response.script, "$.ret=0;\n")

    def test_code_derriere_un_bloc_cgi(self):
        """`[error]0` mais `$.ret=-40101` : c'est le script qui porte l'échec."""
        response = TpLinkSession.parse_response(
            "\r\n".join(["[cgi]0", "$.ret=-40101;", "[error]0"]), [{}]
        )
        self.assertEqual(response.ret, -40101)

    def test_valeur_contenant_des_egals_et_ligne_sans_egal(self):
        """Seul le PREMIER `=` sépare : le reste appartient à la valeur."""
        text = "\r\n".join(
            [
                "[IGD_DEV_INFO#0,0,0,0,0,0#0,0,0,0,0,0]0",
                "description= un texte = avec des égals ",
                "sansEgal",
                "",
                "[error]4503",
            ]
        )
        response = TpLinkSession.parse_response(text, [{}])

        self.assertEqual(response.ret, 4503)
        self.assertEqual(
            response.results[0][0]["description"], " un texte = avec des égals "
        )
        self.assertNotIn("sansEgal", response.results[0][0], "ligne sans `=` ignorée")


class TestAes(unittest.TestCase):
    """AES-128-CBC — interopérabilité avec ``crypto`` de Node."""

    KEY = "1234567890123456"
    IV = "6543210987654321"

    #: Chiffrés PRODUITS PAR NODE (`crypto.createCipheriv('aes-128-cbc', …)`),
    #: figés ici : c'est ce que le routeur attend, au bit près.
    VECTEURS = {
        "8\r\n[/cgi/login#0,0,0,0,0,0#0,0,0,0,0,0]0,2\r\nusername=admin\r\npassword=p@ss\r\n": (
            "Tru8GjiSH2393ZoTxfxporhfuewzCY4fFelOVR13N47qW9Kt5Mj2XcHwAfLyykeH"
            "xzgWBx6bFAI8j+zfMwb0f7w4Jq1UXl9SSylFlj5A45Q="
        ),
    }

    def _session(self) -> TpLinkSession:
        session = TpLinkSession(host="192.168.0.1", password="x")
        session.aes_key, session.aes_iv = self.KEY, self.IV
        session.rsa_n, session.rsa_e = TEST_NN, TEST_EE
        session.hash, session.seq = "d41d8cd98f00b204e9800998ecf8427e", 1
        return session

    def test_aller_retour(self):
        session = self._session()
        for clair in ("", "x" * 16, "accentué éàü — multi-octets", "a\r\nb=c\r\n"):
            body = session._encrypt_body(clair)
            data = body.split("data=")[1].rstrip("\r\n")
            self.assertEqual(session._decrypt_body(data), clair)

    def test_forme_du_corps(self):
        """Le corps posté est exactement `sign=<hex>\\r\\ndata=<base64>\\r\\n`."""
        body = self._session()._encrypt_body("test")
        self.assertTrue(body.startswith("sign="))
        self.assertIn("\r\ndata=", body)
        self.assertTrue(body.endswith("\r\n"))

        sign = body[len("sign=") : body.index("\r\ndata=")]
        # La signature en clair (`key=…&iv=…&h=…&s=…`) dépasse 64 octets : elle
        # occupe DEUX blocs RSA, donc 256 caractères hexadécimaux. Le client JS
        # produit exactement la même longueur.
        self.assertEqual(len(sign), 256, "signature RSA sur deux blocs")
        int(sign, 16)  # lève si ce n'est pas de l'hexadécimal

    def test_signature_inclut_toujours_la_cle(self):
        """Forme LONGUE systématique — voir le docblock de `_encrypt_body`.

        La forme courte (`h=…&s=…`) suppose que le routeur a encore la clé de
        session en mémoire ; dès qu'une autre session s'ouvre il répond 500.
        """
        session = self._session()
        clair = "test"
        body = session._encrypt_body(clair)
        data = body.split("data=")[1].rstrip("\r\n")

        from api.rsa import rsa_encrypt_no_padding

        attendu = rsa_encrypt_no_padding(
            f"key={self.KEY}&iv={self.IV}&h={session.hash}&s={session.seq + len(data)}",
            TEST_NN,
            TEST_EE,
        )
        self.assertEqual(body.split("\r\n")[0], f"sign={attendu}")

    def test_compatible_avec_node(self):
        """Le chiffré Python est identique, octet pour octet, à celui de Node."""
        session = self._session()
        for clair, node_b64 in self.VECTEURS.items():
            body = session._encrypt_body(clair)
            data = body.split("data=")[1].rstrip("\r\n")
            self.assertEqual(data, node_b64, "chiffrement divergent de Node")
            self.assertEqual(session._decrypt_body(node_b64), clair)


if __name__ == "__main__":
    unittest.main()

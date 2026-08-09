import unittest
import zlib

from support import plan

from roomgraph.pdf.content import ContentInterpreter, mat_apply, mat_mul, read_pdf
from roomgraph.pdf.document import Document, _ascii85_decode, _ascii_hex_decode, _run_length_decode
from roomgraph.pdf.lexer import Lexer, Name, Ref, Stream


class TestLexer(unittest.TestCase):
    def test_numbers_and_names(self):
        lex = Lexer(b"12 -3.5 /Foo /A#20B true false")
        self.assertEqual(lex.next_token(), 12)
        self.assertEqual(lex.next_token(), -3.5)
        self.assertEqual(lex.next_token(), Name("Foo"))
        self.assertEqual(lex.next_token(), Name("A B"))
        self.assertIs(lex.next_token(), True)
        self.assertIs(lex.next_token(), False)

    def test_literal_string_escapes(self):
        lex = Lexer(rb"(a\(b\)c\n\101)")
        self.assertEqual(lex.next_token(), b"a(b)c\nA")

    def test_nested_parentheses(self):
        self.assertEqual(Lexer(b"((inner) outer)").next_token(), b"(inner) outer")

    def test_hex_string_pads_odd_digits(self):
        self.assertEqual(Lexer(b"<414>").next_token(), b"A@")

    def test_dictionary_and_reference(self):
        obj = Lexer(b"<< /Type /Page /Parent 4 0 R /N 3 >>").parse_object()
        self.assertEqual(obj["Type"], Name("Page"))
        self.assertEqual(obj["Parent"], Ref(4, 0))
        self.assertEqual(obj["N"], 3)

    def test_array_of_mixed(self):
        arr = Lexer(b"[1 2 0 R (s) /N [3]]").parse_object()
        self.assertEqual(arr[0], 1)
        self.assertEqual(arr[1], Ref(2, 0))
        self.assertEqual(arr[2], b"s")
        self.assertEqual(arr[4], [3])

    def test_comments_are_skipped(self):
        lex = Lexer(b"% a comment\n42")
        self.assertEqual(lex.next_token(), 42)

    def test_integer_not_followed_by_R_is_an_integer(self):
        arr = Lexer(b"[1 2 3]").parse_object()
        self.assertEqual(arr, [1, 2, 3])


class TestFilters(unittest.TestCase):
    def test_ascii_hex(self):
        self.assertEqual(_ascii_hex_decode(b"48656C6C6F>"), b"Hello")

    def test_ascii85(self):
        self.assertEqual(_ascii85_decode(b"87cURD]i,\"Ebo80~>"), b"Hello World!")

    def test_run_length(self):
        self.assertEqual(_run_length_decode(bytes([2, 65, 66, 67, 254, 68, 128])), b"ABCDDD")

    def test_flate_roundtrip_through_document(self):
        payload = b"1 0 0 1 0 0 cm"
        raw = zlib.compress(payload)
        doc = Document(b"%PDF-1.7\n")
        stream = Stream({"Filter": Name("FlateDecode")}, raw)
        self.assertEqual(doc.decode_stream(stream), payload)


class TestMatrix(unittest.TestCase):
    def test_translation_then_scale(self):
        m = mat_mul((1, 0, 0, 1, 10, 20), (2, 0, 0, 2, 0, 0))
        p = mat_apply(m, 1, 1)
        self.assertAlmostEqual(p.x, 22.0)
        self.assertAlmostEqual(p.y, 42.0)


class TestRealFixture(unittest.TestCase):
    def setUp(self):
        self.geo = read_pdf(plan("apartment.pdf"))

    def test_primitives_extracted(self):
        self.assertGreater(len(self.geo.primitives), 20)

    def test_optional_content_layers_survive(self):
        layers = self.geo.layers()
        self.assertIn("A-WALL", layers)
        self.assertIn("A-DOOR", layers)
        self.assertNotIn("", layers, "every primitive should carry its layer")

    def test_text_is_decoded(self):
        texts = [t.text for t in self.geo.texts]
        self.assertIn("PHONG KHACH", texts)
        self.assertIn("9600", texts)

    def test_text_has_position_and_size(self):
        run = next(t for t in self.geo.texts if t.text == "PHONG KHACH")
        self.assertGreater(run.height, 0)
        self.assertGreater(run.origin.x, 0)

    def test_beziers_are_flattened_into_polylines(self):
        arcs = [p for p in self.geo.primitives if len(p.points) > 4]
        self.assertTrue(arcs, "door swing arcs should appear as multi-point polylines")

    def test_page_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            read_pdf(plan("apartment.pdf"), page_index=9)

    def test_pages_have_media_box(self):
        doc = Document.from_path(plan("apartment.pdf"))
        pages = doc.pages()
        self.assertEqual(len(pages), 1)
        self.assertGreater(pages[0].media_box[2], 100)

    def test_interpreter_is_reusable_across_pages(self):
        doc = Document.from_path(plan("apartment.pdf"))
        interp = ContentInterpreter(doc)
        first = interp.run_page(doc.pages()[0])
        second = interp.run_page(doc.pages()[0])
        self.assertEqual(len(first.primitives), len(second.primitives))


class TestMalformedInput(unittest.TestCase):
    def test_empty_file_yields_no_pages(self):
        self.assertEqual(Document(b"").pages(), [])

    def test_truncated_file_does_not_crash(self):
        with open(plan("apartment.pdf"), "rb") as fh:
            data = fh.read()
        doc = Document(data[: len(data) // 2])
        doc.pages()  # must not raise

    def test_garbage_is_survivable(self):
        Document(b"%PDF-1.7\nnot really a pdf at all\n%%EOF").pages()


if __name__ == "__main__":
    unittest.main()

"""Manifest validation and exporter contract tests; detector outputs are fixtures."""

import csv
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from forensics import cli
from forensics.evaluation import evaluate_rows


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / "manifest.csv"

    def read(self, text):
        self.manifest.write_text(text, encoding="utf-8")
        return cli.read_manifest(self.manifest)

    def test_normalizes_required_headers_and_values_and_handles_bom(self):
        rows = self.read("\ufeff source_id , path , label , generator ,note\n image_1 , folder/a.png , 0 , real ,ignored\n")
        self.assertEqual(rows, [{"source_id": "image_1", "path": "folder/a.png", "label": "0", "generator": "real"}])

    def test_whitespace_aliases_are_duplicate_sources(self):
        with self.assertRaisesRegex(ValueError, "unique source_id"):
            self.read("source_id,path,label,generator\nsource,a.png,0,real\n source ,b.png,0,real\n")

    def test_blank_required_values_are_rejected(self):
        columns = ("source_id", "path", "label", "generator")
        for index, field in enumerate(columns):
            values = ["source", "image.png", "0", "real"]
            values[index] = "   "
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                self.read(",".join(columns) + "\n" + ",".join(values) + "\n")

    def test_header_is_validated_even_without_rows(self):
        for text in ("", "source_id,path,label\n", "wrong,columns\n"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "header|required columns"):
                self.read(text)
        with self.assertRaisesRegex(ValueError, "no source images"):
            self.read("source_id,path,label,generator\n\n")

    def test_ambiguous_headers_are_rejected(self):
        for header in ("source_id,path,label,generator, source_id ", "source_id,path,label,generator,"):
            with self.subTest(header=header), self.assertRaisesRegex(ValueError, "header names"):
                self.read(header + "\n")

    def test_invalid_label_and_malformed_rows_are_rejected(self):
        for row in ("a,a.png,AI,model", "a,a.png,0", "a,a.png,0,real,extra"):
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.read("source_id,path,label,generator\n" + row + "\n")

    def test_invalid_manifest_fails_before_detector_setup_or_inference(self):
        invalid_manifests = (
            "source_id,path,label,generator\nsource,a.png,0,real\n source ,b.png,0,real\n",
            "source_id,path,label,generator\n",
            "wrong,columns\n",
        )
        for text in invalid_manifests:
            self.manifest.write_text(text, encoding="utf-8")
            argv = ["forensics.cli", "--manifest", str(self.manifest), "--output", str(self.root / "output")]
            with self.subTest(text=text), patch("sys.argv", argv), patch.object(cli, "choose_detector") as choose, patch.object(cli, "analyze") as analyze, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    cli.main()
                self.assertEqual(raised.exception.code, 2)
                choose.assert_not_called()
                analyze.assert_not_called()
                self.assertFalse((self.root / "output").exists())

    def test_exported_normalized_metadata_is_accepted_by_evaluator(self):
        self.manifest.write_text("source_id,path,label,generator\n real_1 , a.png , 0 , real \n generated_1 , b.png , 1 , fixture_generator \n", encoding="utf-8")
        (self.root / "a.png").write_bytes(b"test fixture a")
        (self.root / "b.png").write_bytes(b"test fixture b")
        reports = [
            {"run_id": f"fixture_{index}", "image": {"sha256": f"fixture_hash_{index}"},
             "variants": [{"round": 0, "score": score}, {"round": 1, "score": score}]}
            for index, score in enumerate((0.2, 0.8))
        ]
        output = self.root / "output"
        argv = ["forensics.cli", "--manifest", str(self.manifest), "--output", str(output), "--rounds", "1"]
        with patch("sys.argv", argv), patch.object(cli, "choose_detector") as choose, patch.object(cli, "analyze", side_effect=reports) as analyze, redirect_stdout(io.StringIO()):
            choose.return_value.available = True
            cli.main()
            self.assertEqual(analyze.call_count, 2)
            self.assertEqual(analyze.call_args_list[0].args[1], "a.png")
        with (output / "predictions.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        report = evaluate_rows(rows)
        self.assertEqual(report["counts"]["independent_sources"], 2)
        self.assertEqual(report["conditions"]["baseline"]["counts"]["by_generator"], {"fixture_generator": 1, "real": 1})


if __name__ == "__main__":
    unittest.main()

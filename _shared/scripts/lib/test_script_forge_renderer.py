import os
import tempfile
import unittest
from pathlib import Path

from script_forge_renderer import query_csv, render_csv_to_markdown, render_template


class QueryCsvTests(unittest.TestCase):
    def test_query_returns_all_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / "data.csv"
            csv_path.write_text(
                "loop_id,status,duration_ms\n"
                "loop-a,done,1200\n"
                "loop-b,failed,3400\n"
                "loop-c,done,800\n",
                encoding="utf-8",
            )
            rows = query_csv(csv_path, "SELECT * FROM data")
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0]["loop_id"], "loop-a")
            self.assertEqual(rows[1]["status"], "failed")

    def test_query_with_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / "data.csv"
            csv_path.write_text(
                "loop_id,status\n"
                "a,done\n"
                "b,failed\n"
                "c,done\n",
                encoding="utf-8",
            )
            rows = query_csv(csv_path, "SELECT * FROM data WHERE status = 'failed'")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["loop_id"], "b")

    def test_query_with_aggregation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / "data.csv"
            csv_path.write_text(
                "loop_id,status\na,done\nb,failed\nc,done\n",
                encoding="utf-8",
            )
            rows = query_csv(csv_path, "SELECT COUNT(*) AS total_rows FROM data")
            self.assertEqual(rows[0]["total_rows"], 3)


class RenderTemplateTests(unittest.TestCase):
    def test_renders_variables_into_template(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            template_path = Path(temporary_directory) / "test.md.j2"
            template_path.write_text(
                "# Report\nTotal: {{ row_count }}\n",
                encoding="utf-8",
            )
            rendered = render_template(template_path, {"row_count": 42})
            self.assertIn("Total: 42", rendered)


class RenderCsvToMarkdownTests(unittest.TestCase):
    def test_renders_default_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / "data.csv"
            csv_path.write_text(
                "loop_id,status\na,done\nb,failed\n",
                encoding="utf-8",
            )
            template_path = Path(temporary_directory) / "report.md.j2"
            template_path.write_text(
                "# Loops\n"
                "{% for row in rows %}\n"
                "- {{ row.loop_id }}: {{ row.status }}\n"
                "{% endfor %}\n",
                encoding="utf-8",
            )
            output_path = Path(temporary_directory) / "report.md"
            result_path = render_csv_to_markdown(csv_path, template_path, output_path)

            self.assertTrue(result_path.exists())
            content = result_path.read_text(encoding="utf-8")
            self.assertIn("- a: done", content)
            self.assertIn("- b: failed", content)

    def test_renders_named_queries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / "data.csv"
            csv_path.write_text(
                "loop_id,status,duration_ms\n"
                "a,done,100\n"
                "b,failed,200\n"
                "c,done,300\n",
                encoding="utf-8",
            )
            template_path = Path(temporary_directory) / "dashboard.md.j2"
            template_path.write_text(
                "# Dashboard\n"
                "Failures: {{ failures | length }}\n"
                "Average duration: {{ statistics[0].average_duration_ms }}ms\n",
                encoding="utf-8",
            )
            output_path = Path(temporary_directory) / "dashboard.md"
            result_path = render_csv_to_markdown(
                csv_path,
                template_path,
                output_path,
                queries={
                    "failures": "SELECT * FROM data WHERE status = 'failed'",
                    "statistics": "SELECT ROUND(AVG(duration_ms), 0) AS average_duration_ms FROM data",
                },
            )

            content = result_path.read_text(encoding="utf-8")
            self.assertIn("Failures: 1", content)
            self.assertIn("Average duration: 200.0ms", content)

    def test_includes_rendered_at_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / "data.csv"
            csv_path.write_text("column_a\nvalue\n", encoding="utf-8")
            template_path = Path(temporary_directory) / "test.md.j2"
            template_path.write_text(
                "Generated: {{ rendered_at }}\n",
                encoding="utf-8",
            )
            output_path = Path(temporary_directory) / "test.md"
            render_csv_to_markdown(csv_path, template_path, output_path)

            content = output_path.read_text(encoding="utf-8")
            self.assertIn("Generated: 20", content)
            self.assertIn("Z", content)

    def test_raises_on_missing_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            template_path = Path(temporary_directory) / "test.md.j2"
            template_path.write_text("hi\n", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                render_csv_to_markdown(
                    Path(temporary_directory) / "nonexistent.csv",
                    template_path,
                    Path(temporary_directory) / "out.md",
                )

    def test_raises_on_missing_template(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path = Path(temporary_directory) / "data.csv"
            csv_path.write_text("column_a\nvalue\n", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                render_csv_to_markdown(
                    csv_path,
                    Path(temporary_directory) / "nonexistent.md.j2",
                    Path(temporary_directory) / "out.md",
                )


if __name__ == "__main__":
    unittest.main()

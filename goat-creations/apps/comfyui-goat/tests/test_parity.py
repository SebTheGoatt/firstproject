"""The Python port builds exactly the same MuAPI requests and prompts as sebastina-core (TypeScript)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import goat_core as core  # noqa: E402

CASES = json.loads((Path(__file__).parent / "golden_cases.json").read_text())


class Parity(unittest.TestCase):
    def test_payloads_match_typescript(self):
        for case in CASES["payloadCases"]:
            with self.subTest(model=case["model"], request=case["request"]):
                self.assertEqual(core.build_payload(case["model"], case["kind"], case["request"]), case["payload"])

    def test_prompts_match_typescript(self):
        for case in CASES["promptCases"]:
            skill = core.SKILLS[case["skill"]]
            got = [core.render_prompt(step["prompt"], skill, case["inputs"]) for step in skill["steps"]]
            with self.subTest(skill=case["skill"], inputs=case["inputs"]):
                self.assertEqual(got, case["prompts"])

    def test_photo_model_without_photo_is_refused(self):
        with self.assertRaisesRegex(core.GoatError, "needs a photo"):
            core.build_payload("ai-image-upscale", "image", {"prompt": ""})


if __name__ == "__main__":
    unittest.main()

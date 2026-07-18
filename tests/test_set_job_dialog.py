import unittest

from PyQt5.QtWidgets import QApplication

from tool import SetJobDialog


class SetJobDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dialog_contains_expected_toolbox_actions(self):
        dialog = SetJobDialog(parent=None)
        actions = [dialog.toolbox_list.item(i).text() for i in range(dialog.toolbox_list.count())]
        self.assertIn("Click Image", actions)
        self.assertIn("Wait Image", actions)
        self.assertIn("Type Text", actions)

    def test_dialog_maps_to_auto_actions(self):
        dialog = SetJobDialog(parent=None)
        self.assertEqual(dialog.get_action_key("Click Image"), "click_image")
        self.assertEqual(dialog.get_action_key("Wait Image"), "wait_image")
        self.assertEqual(dialog.get_action_key("Type Text"), "paste")
        self.assertEqual(dialog.get_action_key("Open App"), "open_app")

    def test_dialog_builds_job_config_payload(self):
        dialog = SetJobDialog(parent=None)
        dialog.workflow_steps = [{"action": "open_app", "path": "browser.exe"}]
        dialog.workflow_data = [dialog.normalize_workflow_step(step) for step in dialog.workflow_steps]
        payload = dialog.save_to_config("demo_job")
        self.assertTrue(payload)

    def test_dialog_normalizes_workflow_step_for_executor(self):
        dialog = SetJobDialog(parent=None)
        step = dialog.normalize_workflow_step({"action": "click_image", "image": "login.png", "timeout": 15, "confidence": 0.9})
        self.assertEqual(step["action"], "click_image")
        self.assertEqual(step["image"], "login.png")
        self.assertEqual(step["timeout"], 15)
        self.assertEqual(step["confidence"], 0.9)


if __name__ == "__main__":
    unittest.main()

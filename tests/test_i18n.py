import unittest
from word_sys_pdf_editor.i18n import _STRINGS, get_supported_languages


class TestI18n(unittest.TestCase):
    def test_all_7_languages_supported(self):
        langs = dict(get_supported_languages())
        expected = ["en", "tr", "fr", "de", "es", "it", "ru"]
        for code in expected:
            self.assertIn(code, langs)
            self.assertIn(code, _STRINGS)

    def test_common_keys_present_in_all_languages(self):
        core_keys = [
            "app_subtitle", "btn_open", "btn_new", "btn_save", "btn_cancel",
            "btn_confirm", "menu_merge_documents", "untitled", "page_info",
            "tool_select", "tool_add_text", "tool_add_image", "tool_drag",
            "btn_guide", "add_page_tip", "color_tip", "bold_tip", "italic_tip",
        ]
        for code in ["en", "tr", "fr", "de", "es", "it", "ru"]:
            d = _STRINGS[code]
            for key in core_keys:
                self.assertIn(key, d, f"Key '{key}' missing from language '{code}'")
                self.assertTrue(d[key], f"Key '{key}' is empty in language '{code}'")

    def test_merge_keys_present_in_all_languages(self):
        merge_keys = [
            "menu_merge_documents", "merge_workspace_title", "merge_workspace_subtitle",
            "merge_source_a", "merge_source_b", "merge_target_doc",
            "merge_empty_source_title", "merge_empty_source_desc",
            "merge_empty_target_title", "merge_empty_target_desc",
            "merge_btn_choose_pdf", "merge_btn_save", "merge_add_page",
            "merge_add_all_tip", "merge_clear_tip", "merge_clear_target_tip",
            "merge_page_count", "merge_remove_page_tip", "merge_move_up_tip",
            "merge_move_down_tip",
        ]
        for code in ["en", "tr", "fr", "de", "es", "it", "ru"]:
            d = _STRINGS[code]
            for key in merge_keys:
                self.assertIn(key, d, f"Merge key '{key}' missing from language '{code}'")
                self.assertTrue(d[key], f"Merge key '{key}' is empty in language '{code}'")


if __name__ == '__main__':
    unittest.main()

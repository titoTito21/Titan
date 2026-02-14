import wx
from translation import _
from datetime import datetime
from api_key_helper import check_api_key

class UserInfoDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("User Information & Subscription"), size=(600, 500))

        self.parent = parent
        self.client = parent.client

        # Check if API key is configured
        if not check_api_key(parent):
            self.Destroy()
            return

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # User info text
        self.info_text = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        vbox.Add(self.info_text, 1, wx.EXPAND | wx.ALL, 10)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.refresh_button = wx.Button(panel, label=_("Refresh"))
        self.refresh_button.Bind(wx.EVT_BUTTON, self.OnRefresh)
        button_sizer.Add(self.refresh_button, 0, wx.ALL, 5)

        self.close_button = wx.Button(panel, label=_("Close"))
        self.close_button.Bind(wx.EVT_BUTTON, self.OnClose)
        button_sizer.Add(self.close_button, 0, wx.ALL, 5)

        vbox.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        panel.SetSizer(vbox)

        # Load user info
        self.LoadUserInfo()

    def LoadUserInfo(self):
        """Load user information from API"""
        try:
            info_lines = []

            # Get subscription info
            try:
                # Try to get subscription - method name may vary
                try:
                    subscription = self.client.user.get_subscription()
                except AttributeError:
                    # Fallback: subscription might be part of user object
                    user_data = self.client.user.get()
                    subscription = user_data.subscription if hasattr(user_data, 'subscription') else None

                if subscription:
                    info_lines.append("=" * 50)
                    info_lines.append(_("SUBSCRIPTION INFORMATION"))
                    info_lines.append("=" * 50)
                    info_lines.append("")

                    if hasattr(subscription, 'tier'):
                        info_lines.append(_(f"Tier: {subscription.tier}"))

                    if hasattr(subscription, 'character_count'):
                        info_lines.append(_(f"Character Count: {subscription.character_count:,}"))

                    if hasattr(subscription, 'character_limit'):
                        info_lines.append(_(f"Character Limit: {subscription.character_limit:,}"))

                    if hasattr(subscription, 'character_count') and hasattr(subscription, 'character_limit'):
                        if subscription.character_limit > 0:
                            percentage = (subscription.character_count / subscription.character_limit) * 100
                            info_lines.append(_(f"Usage: {percentage:.1f}%"))
                            remaining = subscription.character_limit - subscription.character_count
                            info_lines.append(_(f"Characters Remaining: {remaining:,}"))

                    if hasattr(subscription, 'can_extend_character_limit'):
                        info_lines.append(_(f"Can Extend Limit: {subscription.can_extend_character_limit}"))

                    if hasattr(subscription, 'allowed_to_extend_character_limit'):
                        info_lines.append(_(f"Allowed to Extend: {subscription.allowed_to_extend_character_limit}"))

                    if hasattr(subscription, 'next_character_count_reset_unix'):
                        reset_date = datetime.fromtimestamp(subscription.next_character_count_reset_unix)
                        info_lines.append(_(f"Next Reset: {reset_date.strftime('%Y-%m-%d %H:%M:%S')}"))

                    if hasattr(subscription, 'voice_limit'):
                        info_lines.append(_(f"Voice Limit: {subscription.voice_limit}"))

                    if hasattr(subscription, 'professional_voice_limit'):
                        info_lines.append(_(f"Professional Voice Limit: {subscription.professional_voice_limit}"))

                    if hasattr(subscription, 'can_use_instant_voice_cloning'):
                        info_lines.append(_(f"Instant Voice Cloning: {subscription.can_use_instant_voice_cloning}"))

                    if hasattr(subscription, 'can_use_professional_voice_cloning'):
                        info_lines.append(_(f"Professional Voice Cloning: {subscription.can_use_professional_voice_cloning}"))

                    if hasattr(subscription, 'available_models'):
                        info_lines.append("")
                        info_lines.append(_("Available Models:"))
                        for model in subscription.available_models:
                            if hasattr(model, 'model_id'):
                                info_lines.append(f"  - {model.model_id}")
                            else:
                                info_lines.append(f"  - {model}")

                    if hasattr(subscription, 'can_use_delayed_payment_methods'):
                        info_lines.append(_(f"Can Use Delayed Payment: {subscription.can_use_delayed_payment_methods}"))
                else:
                    info_lines.append("=" * 50)
                    info_lines.append(_("SUBSCRIPTION INFORMATION"))
                    info_lines.append("=" * 50)
                    info_lines.append("")
                    info_lines.append(_("Subscription information not available via API."))

            except Exception as e:
                info_lines.append(_(f"Error loading subscription: {str(e)}"))

            info_lines.append("")
            info_lines.append("=" * 50)
            info_lines.append(_("USER INFORMATION"))
            info_lines.append("=" * 50)
            info_lines.append("")

            # Get user info
            try:
                user = self.client.user.get()

                if hasattr(user, 'xi_api_key'):
                    masked_key = user.xi_api_key[:8] + "..." if len(user.xi_api_key) > 8 else user.xi_api_key
                    info_lines.append(_(f"API Key: {masked_key}"))

                if hasattr(user, 'first_name'):
                    info_lines.append(_(f"First Name: {user.first_name}"))

                if hasattr(user, 'is_new_user'):
                    info_lines.append(_(f"New User: {user.is_new_user}"))

                if hasattr(user, 'is_onboarded'):
                    info_lines.append(_(f"Onboarded: {user.is_onboarded}"))

            except Exception as e:
                info_lines.append(_(f"Error loading user info: {str(e)}"))

            # Display all info
            self.info_text.SetValue("\n".join(info_lines))

        except Exception as e:
            wx.MessageBox(_(f"Error loading information: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnRefresh(self, event):
        """Refresh user information"""
        self.LoadUserInfo()
        wx.MessageBox(_("Information refreshed"), _("Success"), wx.OK | wx.ICON_INFORMATION)

    def OnClose(self, event):
        """Close dialog"""
        self.EndModal(wx.ID_OK)


class ModelsDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=_("Available Models"), size=(600, 400))

        self.parent = parent
        self.client = parent.client

        # Check if API key is configured
        if not check_api_key(parent):
            self.Destroy()
            return

        panel = wx.Panel(self)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # Models list
        models_label = wx.StaticText(panel, label=_("Available Models:"))
        vbox.Add(models_label, 0, wx.ALL, 5)

        self.models_list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.models_list.AppendColumn(_("Model ID"), width=250)
        self.models_list.AppendColumn(_("Name"), width=200)
        self.models_list.AppendColumn(_("Languages"), width=150)
        vbox.Add(self.models_list, 1, wx.EXPAND | wx.ALL, 5)

        # Details
        details_label = wx.StaticText(panel, label=_("Model Details:"))
        vbox.Add(details_label, 0, wx.ALL, 5)

        self.details_text = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 100))
        vbox.Add(self.details_text, 0, wx.EXPAND | wx.ALL, 5)

        # Buttons
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.close_button = wx.Button(panel, label=_("Close"))
        self.close_button.Bind(wx.EVT_BUTTON, self.OnClose)
        button_sizer.Add(self.close_button, 0, wx.ALL, 5)

        vbox.Add(button_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        panel.SetSizer(vbox)

        # Bind selection
        self.models_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnModelSelected)

        # Load models
        self.LoadModels()

    def LoadModels(self):
        """Load available models"""
        try:
            self.models_list.DeleteAllItems()
            self.models = []

            # Get models from API - correct method is get() not get_all()
            try:
                models_response = self.client.models.get()
            except AttributeError:
                # Fallback: if models endpoint doesn't exist, use hardcoded list
                wx.MessageBox(_("Models API not available. Showing known models."),
                            _("Information"), wx.OK | wx.ICON_INFORMATION)

                # Hardcoded list of known models
                class SimpleModel:
                    def __init__(self, model_id, name, languages, description=""):
                        self.model_id = model_id
                        self.name = name
                        self.languages = languages
                        self.description = description
                        self.can_do_text_to_speech = True
                        self.can_do_voice_conversion = "sts" in model_id.lower()

                models_response = [
                    SimpleModel("eleven_monolingual_v1", "Eleven Monolingual v1", ["en"], "English only, fast"),
                    SimpleModel("eleven_multilingual_v1", "Eleven Multilingual v1", ["en", "de", "pl", "es", "it", "fr", "pt", "hi"], "Multiple languages v1"),
                    SimpleModel("eleven_multilingual_v2", "Eleven Multilingual v2", ["en", "ja", "zh", "de", "hi", "fr", "ko", "pt", "it", "es", "id", "nl", "tr", "pl", "sv", "bg", "ro", "ar", "cs", "el", "fi", "hr", "ms", "sk", "da", "ta", "uk", "ru"], "Best multilingual model"),
                    SimpleModel("eleven_turbo_v2", "Eleven Turbo v2", ["en", "ja", "zh", "de", "hi", "fr", "ko", "pt", "it", "es", "id", "nl", "tr", "pl", "sv", "bg", "ro", "ar", "cs", "el", "fi", "hr", "ms", "sk", "da", "ta", "uk", "ru"], "Fastest model"),
                    SimpleModel("eleven_turbo_v2_5", "Eleven Turbo v2.5", ["en", "ja", "zh", "de", "hi", "fr", "ko", "pt", "it", "es", "id", "nl", "tr", "pl", "sv", "bg", "ro", "ar", "cs", "el", "fi", "hr", "ms", "sk", "da", "ta", "uk", "ru"], "Latest turbo model"),
                    SimpleModel("eleven_english_sts_v2", "Eleven English STS v2", ["en"], "Speech-to-Speech English"),
                    SimpleModel("eleven_multilingual_sts_v2", "Eleven Multilingual STS v2", ["en", "ja", "zh", "de", "hi", "fr", "ko", "pt", "it", "es", "id", "nl", "tr", "pl", "sv", "bg", "ro", "ar", "cs", "el", "fi", "hr", "ms", "sk", "da", "ta", "uk", "ru"], "Speech-to-Speech multilingual"),
                ]

            for model in models_response:
                model_id = model.model_id if hasattr(model, 'model_id') else str(model)
                name = model.name if hasattr(model, 'name') else ""
                languages = ", ".join(model.languages) if hasattr(model, 'languages') else ""

                index = self.models_list.InsertItem(self.models_list.GetItemCount(), model_id)
                self.models_list.SetItem(index, 1, name)
                self.models_list.SetItem(index, 2, languages[:20] + "..." if len(languages) > 20 else languages)

                self.models.append(model)

        except Exception as e:
            wx.MessageBox(_(f"Error loading models: {str(e)}"), _("Error"), wx.OK | wx.ICON_ERROR)

    def OnModelSelected(self, event):
        """Display model details when selected"""
        selected = self.models_list.GetFirstSelected()
        if selected == -1:
            return

        model = self.models[selected]

        details = []
        if hasattr(model, 'model_id'):
            details.append(f"Model ID: {model.model_id}")
        if hasattr(model, 'name'):
            details.append(f"Name: {model.name}")
        if hasattr(model, 'description'):
            details.append(f"Description: {model.description}")
        if hasattr(model, 'languages'):
            details.append(f"Languages: {', '.join(model.languages)}")
        if hasattr(model, 'can_be_finetuned'):
            details.append(f"Can Be Finetuned: {model.can_be_finetuned}")
        if hasattr(model, 'can_do_text_to_speech'):
            details.append(f"Text-to-Speech: {model.can_do_text_to_speech}")
        if hasattr(model, 'can_do_voice_conversion'):
            details.append(f"Voice Conversion: {model.can_do_voice_conversion}")

        self.details_text.SetValue("\n".join(details))

    def OnClose(self, event):
        """Close dialog"""
        self.EndModal(wx.ID_OK)

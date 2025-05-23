# window.py
#
# Copyright 2024-2025 Jeffser
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Handles the main window
"""

import json
import threading
import os
import re
import base64
import gettext
import uuid
import shutil
import logging
import time
import requests
import sqlite3
import sys
import icu
import numpy as np

from datetime import datetime
from io import BytesIO
from PIL import Image

import gi
import odf.opendocument as odfopen
import odf.table as odftable
from markitdown import MarkItDown
from pydbus import SessionBus, SystemBus, Variant

gi.require_version('GtkSource', '5')
gi.require_version('GdkPixbuf', '2.0')
gi.require_version('Spelling', '1')

from gi.repository import Adw, Gtk, Gdk, GLib, GtkSource, Gio, GdkPixbuf, Spelling, GObject

from . import generic_actions, sql_manager, instance_manager, tool_manager
from .constants import AlpacaFolders, Platforms, SPEACH_RECOGNITION_LANGUAGES, TTS_VOICES, STT_MODELS
from .custom_widgets import message_widget, chat_widget, terminal_widget, dialog_widget, model_manager_widget
from .internal import config_dir, data_dir, cache_dir, source_dir, IN_FLATPAK

logger = logging.getLogger(__name__)

@Gtk.Template(resource_path='/com/jeffser/Alpaca/window.ui')
class AlpacaWindow(Adw.ApplicationWindow):

    __gtype_name__ = 'AlpacaWindow'

    localedir = os.path.join(source_dir, 'locale')

    gettext.bindtextdomain('com.jeffser.Alpaca', localedir)
    gettext.textdomain('com.jeffser.Alpaca')
    _ = gettext.gettext

    #Variables
    attachments = {}

    #Elements
    zoom_spin = Gtk.Template.Child()
    local_model_stack = Gtk.Template.Child()
    available_model_stack = Gtk.Template.Child()
    model_manager_stack = Gtk.Template.Child()
    instance_manager_stack = Gtk.Template.Child()
    main_navigation_view = Gtk.Template.Child()
    local_model_flowbox = Gtk.Template.Child()
    available_model_flowbox = Gtk.Template.Child()
    split_view_overlay_model_manager = Gtk.Template.Child()
    split_view_overlay = Gtk.Template.Child()
    selected_chat_row : Gtk.ListBoxRow = None
    preferences_dialog = Gtk.Template.Child()
    file_preview_dialog = Gtk.Template.Child()
    preview_file_bin = Gtk.Template.Child()
    welcome_carousel = Gtk.Template.Child()
    welcome_previous_button = Gtk.Template.Child()
    welcome_next_button = Gtk.Template.Child()
    main_overlay = Gtk.Template.Child()
    chat_stack = Gtk.Template.Child()
    message_text_view = None
    message_text_view_scrolled_window = Gtk.Template.Child()
    quick_ask_text_view_scrolled_window = Gtk.Template.Child()
    action_button_stack = Gtk.Template.Child()
    attachment_container = Gtk.Template.Child()
    attachment_box = Gtk.Template.Child()
    attachment_button = Gtk.Template.Child()
    chat_right_click_menu = Gtk.Template.Child()
    send_message_menu = Gtk.Template.Child()
    attachment_menu = Gtk.Template.Child()
    file_preview_open_button = Gtk.Template.Child()
    file_preview_remove_button = Gtk.Template.Child()
    model_searchbar = Gtk.Template.Child()
    searchentry_models = Gtk.Template.Child()
    model_search_button = Gtk.Template.Child()
    message_searchbar = Gtk.Template.Child()
    searchentry_messages = Gtk.Template.Child()
    title_stack = Gtk.Template.Child()
    title_no_model_button = Gtk.Template.Child()
    model_filter_button = Gtk.Template.Child()

    file_filter_db = Gtk.Template.Child()
    file_filter_gguf = Gtk.Template.Child()
    file_filter_image = Gtk.FileFilter()
    file_filter_image.add_pixbuf_formats()

    chat_list_container = Gtk.Template.Child()
    chat_list_box = None
    model_manager = None

    background_switch = Gtk.Template.Child()
    powersaver_warning_switch = Gtk.Template.Child()
    mic_auto_send_switch = Gtk.Template.Child()
    mic_language_combo = Gtk.Template.Child()
    mic_model_combo = Gtk.Template.Child()
    tts_voice_combo = Gtk.Template.Child()

    banner = Gtk.Template.Child()

    terminal_scroller = Gtk.Template.Child()
    terminal_dialog = Gtk.Template.Child()
    terminal_dir_button = Gtk.Template.Child()

    quick_ask = Gtk.Template.Child()
    quick_ask_overlay = Gtk.Template.Child()
    quick_ask_save_button = Gtk.Template.Child()

    model_creator_stack = Gtk.Template.Child()
    model_creator_base = Gtk.Template.Child()
    model_creator_profile_picture = Gtk.Template.Child()
    model_creator_name = Gtk.Template.Child()
    model_creator_tag = Gtk.Template.Child()
    model_creator_context = Gtk.Template.Child()
    model_creator_imagination = Gtk.Template.Child()
    model_creator_focus = Gtk.Template.Child()
    model_dropdown = Gtk.Template.Child()
    notice_dialog = Gtk.Template.Child()

    instance_preferences_page = Gtk.Template.Child()
    instance_listbox = Gtk.Template.Child()
    available_models_stack_page = Gtk.Template.Child()
    model_creator_stack_page = Gtk.Template.Child()
    install_ollama_button = Gtk.Template.Child()
    tool_listbox = Gtk.Template.Child()
    model_manager_bottom_view_switcher = Gtk.Template.Child()
    model_manager_top_view_switcher = Gtk.Template.Child()
    last_selected_instance_row = None

    sql_instance = sql_manager.Instance(os.path.join(data_dir, "alpaca.db"))
    mid = MarkItDown(enable_plugins=False)

    # tts
    message_dictated = None

    @Gtk.Template.Callback()
    def microphone_toggled(self, button):
        language=self.sql_instance.get_preference('mic_language')
        text_view = list(button.get_parent().get_parent())[0].get_child()
        buffer = text_view.get_buffer()
        model_name = os.getenv("ALPACA_SPEECH_MODEL", "base")

        def recognize_audio(model, audio_data, current_iter):
            result = model.transcribe(audio_data, language=language)
            if len(result.get("text").encode('utf8')) == 0:
                self.mic_timeout += 1
            else:
                GLib.idle_add(buffer.insert, current_iter, result.get("text"), len(result.get("text").encode('utf8')))
                self.mic_timeout = 0

        def run_mic(pulling_model:Gtk.Widget=None):
            GLib.idle_add(button.get_parent().set_visible_child_name, "loading")
            import whisper
            import pyaudio
            GLib.idle_add(button.add_css_class, 'accent')

            samplerate=16000
            p = pyaudio.PyAudio()
            model = None

            self.mic_timeout=0

            try:
                model = whisper.load_model(model_name, download_root=os.path.join(data_dir, 'whisper'))
                if pulling_model:
                    GLib.idle_add(pulling_model.update_progressbar, {'status': 'success'})
            except Exception as e:
                dialog_widget.simple_error(_('Speech Recognition Error'), _('An error occurred while pulling speech recognition model'), e)
                logger.error(e)
            GLib.idle_add(button.get_parent().set_visible_child_name, "button")

            if model:
                stream = p.open(
                    format=pyaudio.paInt16,
                    rate=samplerate,
                    input=True,
                    frames_per_buffer=1024,
                    channels=1
                )

                try:
                    while button.get_active():
                        frames = []
                        for i in range(0, int(samplerate / 1024 * 2)):
                            data = stream.read(1024, exception_on_overflow=False)
                            frames.append(np.frombuffer(data, dtype=np.int16))
                        audio_data = np.concatenate(frames).astype(np.float32) / 32768.0
                        threading.Thread(target=recognize_audio, args=(model, audio_data, buffer.get_end_iter())).start()

                        if self.mic_timeout >= 2 and self.sql_instance.get_preference('mic_auto_send', False) and buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False):
                            if text_view.get_name() == 'main_text_view':
                                GLib.idle_add(self.send_message)
                            elif text_view.get_name() == 'quick_chat_text_view':
                                GLib.idle_add(self.quick_chat, buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False), 0)
                            break

                except Exception as e:
                    dialog_widget.simple_error(_('Speech Recognition Error'), _('An error occurred while using speech recognition'), e)
                    logger.error(e)
                finally:
                    stream.stop_stream()
                    stream.close()
                    p.terminate()

            if button.get_active():
                button.set_active(False)

        def prepare_download():
            pulling_model = model_manager_widget.pulling_model(model_name, model_manager_widget.add_speech_to_text_model, False)
            self.local_model_flowbox.prepend(pulling_model)
            #pulling_model.update_progressbar({"status": "Pulling {}".format(model_name.title()), 'digest': '{}.pt'.format(model_name)})
            threading.Thread(target=run_mic, args=(pulling_model,)).start()

        if button.get_active():
            if os.path.isfile(os.path.join(data_dir, 'whisper', '{}.pt'.format(model_name))):
                threading.Thread(target=run_mic).start()
            else:
                dialog_widget.simple(
                    _("Download Speech Recognition Model"),
                    _("To use speech recognition you'll need to download a special model ({})").format(STT_MODELS.get(model_name, '~151mb')),
                    prepare_download,
                    _("Download Model")
                )
        else:
            button.remove_css_class('accent')
            button.set_sensitive(False)
            GLib.timeout_add(2000, lambda button: button.set_sensitive(True) and False, button)


    @Gtk.Template.Callback()
    def closing_notice(self, dialog):
        self.sql_instance.insert_or_update_preferences({"last_notice_seen": dialog.get_name()})

    @Gtk.Template.Callback()
    def add_instance(self, button):
        def selected(ins):
            if ins.instance_type == 'ollama:managed' and not shutil.which('ollama'):
                dialog_widget.simple(
                    _("Ollama Was Not Found"),
                    _("To add a managed Ollama instance, you must have Ollama installed locally in your device, this is a simple process and should not take more than 5 minutes."),
                    lambda: Gio.AppInfo.launch_default_for_uri('https://github.com/Jeffser/Alpaca/wiki/Installing-Ollama'),
                    _("Open Tutorial in Web Browser")
                )
            else:
                tbv=Adw.ToolbarView()
                tbv.add_top_bar(Adw.HeaderBar())
                tbv.set_content(ins().get_preferences_page())
                self.main_navigation_view.push(Adw.NavigationPage(title=_('Add Instance'), tag='instance', child=tbv))

        options = {}
        for ins_type in instance_manager.ready_instances:
            options[ins_type.instance_type_display] = ins_type

        dialog_widget.simple_dropdown(
            _("Add Instance"),
            _("Select a type of instance to add"),
            lambda option, options=options: selected(options[option]),
            options.keys()
        )

    @Gtk.Template.Callback()
    def instance_changed(self, listbox, row):
        """
        This method is called when the selected instance changes.
        It updates corresponding UI elements, selections and internal variables.
        """

        def change_instance():
            if self.last_selected_instance_row:
                self.last_selected_instance_row.instance.stop()

            self.last_selected_instance_row = row

            model_manager_widget.update_local_model_list()
            model_manager_widget.update_available_model_list()

            self.available_models_stack_page.set_visible(len(model_manager_widget.available_models) > 0)
            self.model_creator_stack_page.set_visible(len(model_manager_widget.available_models) > 0)

            if row:
                self.sql_instance.insert_or_update_preferences({'selected_instance': row.instance.instance_id})

            self.chat_list_box.update_profile_pictures()
            visible_model_manger_switch = len([p for p in self.model_manager_stack.get_pages() if p.get_visible()]) > 1

            self.model_manager_bottom_view_switcher.set_visible(visible_model_manger_switch)
            self.model_manager_top_view_switcher.set_visible(visible_model_manger_switch)
        if listbox.get_sensitive():
            threading.Thread(target=change_instance).start()


    @Gtk.Template.Callback()
    def model_creator_accept(self, button):
        profile_picture = self.model_creator_profile_picture.get_subtitle()
        model_name = '{}:{}'.format(self.model_creator_name.get_text(), self.model_creator_tag.get_text() if self.model_creator_tag.get_text() else 'latest').replace(' ', '-').lower()
        context_buffer = self.model_creator_context.get_buffer()
        system_message = context_buffer.get_text(context_buffer.get_start_iter(), context_buffer.get_end_iter(), False).replace('"', '\\"')
        top_k = self.model_creator_imagination.get_value()
        top_p = self.model_creator_focus.get_value() / 100

        found_models = [row.model for row in list(self.model_dropdown.get_model()) if row.model.get_name() == model_name]
        if not found_models:
            if profile_picture:
                self.sql_instance.insert_or_update_model_picture(model_name, self.get_content_of_file(profile_picture, 'profile_picture'))

            data_json = {
                'model': model_name,
                'system': system_message,
                'parameters': {
                    'top_k': top_k,
                    'top_p': top_p
                },
                'stream': True
            }

            if self.model_creator_base.get_subtitle():
                gguf_path = self.model_creator_base.get_subtitle()
                model_manager_widget.create_model(data_json, gguf_path)
            else:
                data_json['from'] = self.convert_model_name(self.model_creator_base.get_selected_item().get_string(), 1)
                model_manager_widget.create_model(data_json)

    @Gtk.Template.Callback()
    def model_creator_cancel(self, button):
        self.model_creator_stack.set_visible_child_name('introduction')

    @Gtk.Template.Callback()
    def model_creator_load_profile_picture(self, button):
        dialog_widget.simple_file([self.file_filter_image], lambda file: self.model_creator_profile_picture.set_subtitle(file.get_path()))

    @Gtk.Template.Callback()
    def model_creator_base_changed(self, comborow, params):
        model_name = comborow.get_selected_item().get_string()
        if model_name != 'GGUF' and not comborow.get_subtitle():
            model_name = self.convert_model_name(model_name, 1)

            GLib.idle_add(self.model_creator_name.set_text, model_name.split(':')[0])
            GLib.idle_add(self.model_creator_tag.set_text, 'custom')

            system = None
            modelfile = None

            found_models = [row.model for row in list(self.model_dropdown.get_model()) if row.model.get_name() == model_name]
            if found_models:
                system = found_models[0].data.get('system')
                modelfile = found_models[0].data.get('modelfile')

            if system:
                context_buffer = self.model_creator_context.get_buffer()
                GLib.idle_add(context_buffer.delete, context_buffer.get_start_iter(), context_buffer.get_end_iter())
                GLib.idle_add(context_buffer.insert_at_cursor, system, len(system))

            if modelfile:
                for line in modelfile.splitlines():
                    if line.startswith('PARAMETER top_k'):
                        top_k = int(line.split(' ')[2])
                        GLib.idle_add(self.model_creator_imagination.set_value, top_k)
                    elif line.startswith('PARAMETER top_p'):
                        top_p = int(float(line.split(' ')[2]) * 100)
                        GLib.idle_add(self.model_creator_focus.set_value, top_p)

    @Gtk.Template.Callback()
    def model_creator_gguf(self, button):
        def result(file):
            try:
                file_path = file.get_path()
            except Exception as e:
                return
            context_buffer = self.model_creator_context.get_buffer()
            context_buffer.delete(context_buffer.get_start_iter(), context_buffer.get_end_iter())
            self.model_creator_profile_picture.set_subtitle('')
            string_list = Gtk.StringList()
            string_list.append('GGUF')
            self.model_creator_base.set_model(string_list)
            self.model_creator_base.set_subtitle(file_path)
            self.model_creator_stack.set_visible_child_name('content')

        dialog_widget.simple_file([self.file_filter_gguf], result)

    @Gtk.Template.Callback()
    def model_creator_existing(self, button, selected_model:str=None):
        GLib.idle_add(self.model_manager_stack.set_visible_child_name, 'model_creator')
        context_buffer = self.model_creator_context.get_buffer()
        context_buffer.delete(context_buffer.get_start_iter(), context_buffer.get_end_iter())
        GLib.idle_add(self.model_creator_profile_picture.set_subtitle, '')
        GLib.idle_add(self.model_creator_base.set_subtitle, '')
        string_list = Gtk.StringList()
        if selected_model:
            GLib.idle_add(string_list.append, self.convert_model_name(selected_model, 0))
        else:
            [GLib.idle_add(string_list.append, value.model_title) for value in model_manager_widget.get_local_models().values()]
        GLib.idle_add(self.model_creator_base.set_model, string_list)
        GLib.idle_add(self.model_creator_stack.set_visible_child_name, 'content')

    @Gtk.Template.Callback()
    def model_manager_stack_changed(self, viewstack, params):
        self.local_model_flowbox.unselect_all()
        self.available_model_flowbox.unselect_all()
        self.model_creator_stack.set_visible_child_name('introduction')
        self.model_search_button.set_sensitive(viewstack.get_visible_child_name() not in ('model_creator', 'instances'))
        self.model_search_button.set_active(self.model_search_button.get_active() and viewstack.get_visible_child_name() not in ('model_creator', 'instances'))

    @Gtk.Template.Callback()
    def model_manager_child_activated(self, flowbox, selected_child):
        self.split_view_overlay_model_manager.set_show_sidebar(selected_child)
        self.set_focus(selected_child.get_child().get_default_widget())

    @Gtk.Template.Callback()
    def model_manager_child_selected(self, flowbox):
        def set_default_sidebar():
            time.sleep(1)
            if not self.split_view_overlay_model_manager.get_show_sidebar():
                tbv = Adw.ToolbarView()
                tbv.add_top_bar(
                    Adw.HeaderBar(
                        show_back_button=False,
                        show_title=False
                    )
                )
                tbv.set_content(Adw.StatusPage(icon_name='brain-augemnted-symbolic'))
                GLib.idle_add(self.split_view_overlay_model_manager.set_sidebar, tbv)

        selected_children = flowbox.get_selected_children()
        if len(selected_children) > 0:
            self.split_view_overlay_model_manager.set_show_sidebar(True)
            model = selected_children[0].get_child()
            buttons, content = model.get_page()

            tbv = Adw.ToolbarView()
            hb = Adw.HeaderBar(
                show_back_button=False,
                show_title=False
            )
            tbv.add_top_bar(hb)
            for btn in buttons:
                hb.pack_start(btn)
            tbv.set_content(Gtk.ScrolledWindow(
                vexpand=True
            ))
            tbv.get_content().set_child(content)
            self.split_view_overlay_model_manager.set_sidebar(tbv)
        else:
            self.split_view_overlay_model_manager.set_show_sidebar(False)
            threading.Thread(target=set_default_sidebar).start()


    @Gtk.Template.Callback()
    def closing_terminal(self, dialog):
        dialog.get_child().get_content().get_child().feed_child(b"\x03")
        dialog.force_close()

    @Gtk.Template.Callback()
    def stop_message(self, button=None):
        self.chat_list_box.get_current_chat().stop_message()

    @Gtk.Template.Callback()
    def send_message(self, button=None, mode:int=0): #mode 0=user 1=system 2=tool
        if button and not button.get_visible():
            return
        if not self.message_text_view.get_buffer().get_text(self.message_text_view.get_buffer().get_start_iter(), self.message_text_view.get_buffer().get_end_iter(), False):
            return
        current_chat = self.chat_list_box.get_current_chat()
        if current_chat.busy == True:
            return

        if self.get_current_instance().instance_type == 'empty':
            self.get_application().lookup_action('instance_manager').activate()
            return

        current_model = model_manager_widget.get_selected_model().get_name()
        if mode == 2 and len(tool_manager.get_enabled_tools()) == 0:
            self.show_toast(_("No tools enabled."), self.main_overlay, 'app.tool_manager', _('Open Tool Manager'))
            return
        if 'ollama' in self.get_current_instance().instance_type and mode == 2 and 'tools' not in model_manager_widget.available_models.get(current_model.split(':')[0], {}).get('categories', []):
            self.show_toast(_("'{}' does not support tools.").format(self.convert_model_name(current_model, 0)), self.main_overlay, 'app.model_manager', _('Open Model Manager'))
            return
        if current_model is None:
            self.show_toast(_("Please select a model before chatting"), self.main_overlay)
            return

        self.chat_list_box.send_tab_to_top(self.chat_list_box.get_selected_row())

        message_id = self.generate_uuid()

        raw_message = self.message_text_view.get_buffer().get_text(self.message_text_view.get_buffer().get_start_iter(), self.message_text_view.get_buffer().get_end_iter(), False)
        m_element = current_chat.add_message(message_id, datetime.now(), None, mode==1)

        for name, content in self.attachments.items():
            attachment = m_element.add_attachment(name, content['type'], content['content'])
            self.sql_instance.add_attachment(m_element, attachment)
            content["button"].get_parent().remove(content["button"])
        self.attachments = {}
        self.attachment_box.set_visible(False)

        m_element.set_text(raw_message)

        self.sql_instance.insert_or_update_message(m_element)

        self.message_text_view.get_buffer().set_text("", 0)

        if mode==0:
            bot_id=self.generate_uuid()
            m_element_bot = current_chat.add_message(bot_id, datetime.now(), current_model, False)
            m_element_bot.set_text()
            m_element_bot.footer.options_button.set_sensitive(False)
            self.sql_instance.insert_or_update_message(m_element_bot)
            threading.Thread(target=self.get_current_instance().generate_message, args=(m_element_bot, current_model)).start()
        elif mode==1:
            current_chat.set_visible_child_name('content')
        elif mode==2:
            bot_id=self.generate_uuid()
            m_element_bot = current_chat.add_message(bot_id, datetime.now(), current_model, False)
            m_element_bot.set_text()
            m_element_bot.footer.options_button.set_sensitive(False)
            self.sql_instance.insert_or_update_message(m_element_bot)
            threading.Thread(target=self.get_current_instance().use_tools, args=(m_element_bot, current_model)).start()

    @Gtk.Template.Callback()
    def welcome_carousel_page_changed(self, carousel, index):
        logger.debug("Showing welcome carousel")
        if index == 0:
            self.welcome_previous_button.set_sensitive(False)
        else:
            self.welcome_previous_button.set_sensitive(True)
        if index == carousel.get_n_pages()-1:
            self.welcome_next_button.set_label(_("Close"))
            self.welcome_next_button.set_tooltip_text(_("Close"))
        else:
            self.welcome_next_button.set_label(_("Next"))
            self.welcome_next_button.set_tooltip_text(_("Next"))

    @Gtk.Template.Callback()
    def welcome_previous_button_activate(self, button):
        self.welcome_carousel.scroll_to(self.welcome_carousel.get_nth_page(self.welcome_carousel.get_position()-1), True)

    @Gtk.Template.Callback()
    def welcome_next_button_activate(self, button):
        if button.get_label() == "Next":
            self.welcome_carousel.scroll_to(self.welcome_carousel.get_nth_page(self.welcome_carousel.get_position()+1), True)
        else:
            self.sql_instance.insert_or_update_preferences({'skip_welcome_page': True})
            self.prepare_alpaca()

    @Gtk.Template.Callback()
    def zoom_changed(self, spinner, force:bool=False):
        if force or self.sql_instance.get_preference('zoom', 100) != int(spinner.get_value()):
            threading.Thread(target=self.sql_instance.insert_or_update_preferences, args=({'zoom': int(spinner.get_value())},)).start()
            settings = Gtk.Settings.get_default()
            settings.reset_property('gtk-xft-dpi')
            settings.set_property('gtk-xft-dpi',  settings.get_property('gtk-xft-dpi') + (int(spinner.get_value()) - 100) * 400)

    @Gtk.Template.Callback()
    def switch_run_on_background(self, switch, user_data):
        if switch.get_sensitive():
            self.set_hide_on_close(switch.get_active())
            self.sql_instance.insert_or_update_preferences({'run_on_background': switch.get_active()})
    
    @Gtk.Template.Callback()
    def switch_mic_auto_send(self, switch, user_data):
        if switch.get_sensitive():
            self.sql_instance.insert_or_update_preferences({'mic_auto_send': switch.get_active()})

    @Gtk.Template.Callback()
    def selected_mic_model(self, combo, user_data):
        if combo.get_sensitive():
            model = combo.get_selected_item().get_string().split(' (')[0].lower()
            if model:
                self.sql_instance.insert_or_update_preferences({'mic_model': model})

    @Gtk.Template.Callback()
    def selected_mic_language(self, combo, user_data):
        if combo.get_sensitive():
            language = combo.get_selected_item().get_string().split(' (')[-1][:-1]
            if language:
                self.sql_instance.insert_or_update_preferences({'mic_language': language})

    @Gtk.Template.Callback()
    def selected_tts_voice(self, combo, user_data):
        if combo.get_sensitive():
            language = TTS_VOICES.get(combo.get_selected_item().get_string())
            if language:
                self.sql_instance.insert_or_update_preferences({'tts_voice': language})

    @Gtk.Template.Callback()
    def switch_powersaver_warning(self, switch, user_data):
        if switch.get_sensitive():
            if switch.get_active():
                self.banner.set_revealed(Gio.PowerProfileMonitor.dup_default().get_power_saver_enabled() and self.get_current_instance().instance_type == 'ollama:managed')
            else:
                self.banner.set_revealed(False)
            self.sql_instance.insert_or_update_preferences({'powersaver_warning': switch.get_active()})

    @Gtk.Template.Callback()
    def closing_app(self, user_data):
        def close():
            selected_chat = self.chat_list_box.get_selected_row().chat_window.get_name()
            self.sql_instance.insert_or_update_preferences({'selected_chat': selected_chat})
            self.get_current_instance().stop()
            if self.message_dictated:
                self.message_dictated.footer.popup.tts_button.set_active(False)
            self.get_application().quit()

        def switch_to_hide():
            self.set_hide_on_close(True)
            self.close() #Recalls this function

        if self.get_hide_on_close():
            logger.info("Hiding app...")
        else:
            logger.info("Closing app...")
            if any([chat.chat_window.busy for chat in self.chat_list_box.tab_list]) or any([el for el in list(self.local_model_flowbox) if isinstance(el.get_child(), model_manager_widget.pulling_model)]):
                options = {
                    _('Cancel'): {'default': True},
                    _('Hide'): {'callback': switch_to_hide},
                    _('Close'): {'callback': close, 'appearance': 'destructive'},
                }
                dialog_widget.Options(
                    _('Close Alpaca?'),
                    _('A task is currently in progress. Are you sure you want to close Alpaca?'),
                    list(options.keys())[0],
                    options,
                )
                return True
            else:
                close()

    @Gtk.Template.Callback()
    def link_button_handler(self, button):
        try:
            Gio.AppInfo.launch_default_for_uri(button.get_name())
        except Exception as e:
            logger.error(e)

    @Gtk.Template.Callback()
    def model_search_changed(self, entry):
        filtered_categories = set()
        if self.model_filter_button.get_popover():
            filtered_categories = set([c.get_name() for c in list(self.model_filter_button.get_popover().get_child()) if c.get_active()])
        results_local = False

        if len(list(self.local_model_flowbox)) > 0:
            for model in list(self.local_model_flowbox):
                string_search = re.search(entry.get_text(), model.get_child().get_search_string(), re.IGNORECASE)
                category_filter = len(filtered_categories) == 0 or model.get_child().get_search_categories() & filtered_categories or not self.model_searchbar.get_search_mode()
                model.set_visible(string_search and category_filter)
                results_local = results_local or model.get_visible()
                if not model.get_visible() and model in self.local_model_flowbox.get_selected_children():
                    self.local_model_flowbox.unselect_all()
            self.local_model_stack.set_visible_child_name('content' if results_local else 'no-results')
        else:
            self.local_model_stack.set_visible_child_name('no-models')

        results_available = False
        if len(model_manager_widget.available_models) > 0:
            self.available_models_stack_page.set_visible(True)
            self.model_creator_stack_page.set_visible(True)
            for model in list(self.available_model_flowbox):
                string_search = re.search(entry.get_text(), model.get_child().get_search_string(), re.IGNORECASE)
                category_filter = len(filtered_categories) == 0 or model.get_child().get_search_categories() & filtered_categories or not self.model_searchbar.get_search_mode()
                model.set_visible(string_search and category_filter)
                results_available = results_available or model.get_visible()
                if not model.get_visible() and model in self.available_model_flowbox.get_selected_children():
                    self.available_model_flowbox.unselect_all()
            self.available_model_stack.set_visible_child_name('content' if results_available else 'no-results')
        else:
            self.available_models_stack_page.set_visible(False)
            self.model_creator_stack_page.set_visible(False)

    @Gtk.Template.Callback()
    def message_search_changed(self, entry, current_chat=None):
        search_term=entry.get_text()
        results = 0
        if not current_chat:
            current_chat = self.chat_list_box.get_current_chat()
        if current_chat:
            try:
                for key, message in current_chat.messages.items():
                    if message and message.text:
                        message.set_visible(re.search(search_term, message.text, re.IGNORECASE))
                        for block in message.content_children:
                            if isinstance(block, message_widget.text_block):
                                if search_term:
                                    highlighted_text = re.sub(f"({re.escape(search_term)})", r"<span background='yellow' bgalpha='30%'>\1</span>", block.get_text(),flags=re.IGNORECASE)
                                    block.set_markup(highlighted_text)
                                else:
                                    block.set_markup(block.get_text())
            except Exception as e:
                pass

    def convert_model_name(self, name:str, mode:int): # mode=0 name:tag -> Name (tag)   |   mode=1 Name (tag) -> name:tag   |   mode=2 name:tag -> name, tag
        try:
            if mode == 0:
                if ':' in name:
                    name = name.split(':')
                    return '{} ({})'.format(name[0].replace('-', ' ').title(), name[1].replace('-', ' ').title())
                else:
                    return name.replace('-', ' ').title()
            elif mode == 1:
                if ' (' in name:
                    name = name.split(' (')
                    return '{}:{}'.format(name[0].replace(' ', '-').lower(), name[1][:-1].replace(' ', '-').lower())
                else:
                    return name.replace(' ', '-').lower()
            elif mode == 2:
                if ':' in name:
                    name = name.split(':')
                    return name[0].replace('-', ' ').title(), name[1].replace('-', ' ').title()
                else:
                    return name.replace('-', ' ').title(), None


        except Exception as e:
            pass

    @Gtk.Template.Callback()
    def quick_ask_save(self, button):
        self.quick_ask.close()
        chat = self.quick_ask_overlay.get_child()
        chat_name = self.generate_numbered_name(chat.get_name(), [tab.chat_window.get_name() for tab in self.chat_list_box.tab_list])
        new_chat = self.chat_list_box.new_chat(chat_name)
        for message in chat.messages.values():
            self.sql_instance.insert_or_update_message(message, new_chat.chat_id)
        threading.Thread(target=new_chat.load_chat_messages).start()
        self.present()

    @Gtk.Template.Callback()
    def closing_quick_ask(self, user_data):
        if not self.get_visible():
            self.close()

    def on_clipboard_paste(self, textview):
        logger.debug("Pasting from clipboard")
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.read_text_async(None, lambda clipboard, result: self.cb_text_received(clipboard.read_text_finish(result)))
        clipboard.read_texture_async(None, self.cb_image_received)

    def check_alphanumeric(self, editable, text, length, position, allowed_chars):
        if length == 1:
            new_text = ''.join([char for char in text if char.isalnum() or char in allowed_chars])
            if new_text != text:
                editable.stop_emission_by_name("insert-text")

    def show_toast(self, message:str, overlay, action:str=None, action_name:str=None):
        logger.info(message)
        toast = Adw.Toast(
            title=message,
            timeout=2
        )
        if action and action_name:
            toast.set_action_name(action)
            toast.set_button_label(action_name)
        overlay.add_toast(toast)

    def show_notification(self, title:str, body:str, icon:Gio.ThemedIcon=None):
        if not self.is_active() and not self.quick_ask.is_active():
            body = body.replace('<span>', '').replace('</span>', '')
            logger.info(f"{title}, {body}")
            notification = Gio.Notification.new(title)
            notification.set_body(body)
            if icon:
                notification.set_icon(icon)
            self.get_application().send_notification(None, notification)

    def preview_file(self, file_name:str, file_content:str, file_type:str, show_remove:bool, root:Gtk.Widget):
        logger.info(f"Previewing file: {file_name}")
        if show_remove:
            self.file_preview_remove_button.set_visible(True)
            self.file_preview_remove_button.set_name(file_name)
        else:
            self.file_preview_remove_button.set_visible(False)
        if file_content:
            if file_type == 'image':
                image_element = Gtk.Image(
                    hexpand=True,
                    vexpand=True,
                    css_classes=['rounded_image']
                )
                image_data = base64.b64decode(file_content)
                loader = GdkPixbuf.PixbufLoader.new()
                loader.write(image_data)
                loader.close()
                pixbuf = loader.get_pixbuf()
                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                image_element.set_from_paintable(texture)
                image_element.set_size_request(360, 360)
                image_element.set_overflow(1)
                self.preview_file_bin.set_child(image_element)
                self.file_preview_dialog.set_title(file_name)
                self.file_preview_open_button.set_visible(False)
            else:
                msg_element = message_widget.message(message_id=0, model="Alpaca File Preview", show_footer=False)
                msg_element.set_text(file_content)
                msg_element.set_vexpand(True)
                self.preview_file_bin.set_child(msg_element)

                if file_type == 'youtube':
                    self.file_preview_dialog.set_title(file_content.split('\n')[0])
                    self.file_preview_open_button.set_name(file_content.split('\n')[2])
                    self.file_preview_open_button.set_visible(True)
                elif file_type == 'website':
                    self.file_preview_dialog.set_title(file_name)
                    self.file_preview_open_button.set_name(file_content.split('\n')[0])
                    self.file_preview_open_button.set_visible(True)
                else:
                    self.file_preview_dialog.set_title(file_name)
                    self.file_preview_open_button.set_visible(False)
            self.file_preview_dialog.present(root)

    def switch_send_stop_button(self, send:bool):
        self.action_button_stack.set_visible_child_name('send' if send else 'stop')

    def load_history(self):
        logger.debug("Loading history")
        selected_chat = self.sql_instance.get_preference('selected_chat')
        chats = self.sql_instance.get_chats()
        if len(chats) > 0:
            threads = []
            if selected_chat not in [row[1] for row in chats]:
                selected_chat = chats[0][1]
            for row in chats:
                chat_container =self.chat_list_box.append_chat(row[1], row[0])
                if row[1] == selected_chat:
                    self.chat_list_box.select_row(self.chat_list_box.tab_list[-1])
        else:
            self.chat_list_box.new_chat()

    def generate_numbered_name(self, chat_name:str, compare_list:list) -> str:
        if chat_name in compare_list:
            for i in range(len(compare_list)):
                if "." in chat_name:
                    if f"{'.'.join(chat_name.split('.')[:-1])} {i+1}.{chat_name.split('.')[-1]}" not in compare_list:
                        chat_name = f"{'.'.join(chat_name.split('.')[:-1])} {i+1}.{chat_name.split('.')[-1]}"
                        break
                else:
                    if f"{chat_name} {i+1}" not in compare_list:
                        chat_name = f"{chat_name} {i+1}"
                        break
        return chat_name

    def generate_uuid(self) -> str:
        return f"{datetime.today().strftime('%Y%m%d%H%M%S%f')}{uuid.uuid4().hex}"

    def get_content_of_file(self, file_path, file_type):
        if not os.path.exists(file_path): return None
        if file_type in ('image', 'profile_picture'):
            max_size = {'image': 640, 'profile_picture': 128}.get(file_type)
            try:
                with Image.open(file_path) as img:
                    width, height = img.size
                    if width > height:
                        new_width = max_size
                        new_height = int((max_size / width) * height)
                    else:
                        new_height = max_size
                        new_width = int((max_size / height) * width)
                    resized_img = img.resize((new_width, new_height), Image.LANCZOS)
                    with BytesIO() as output:
                        resized_img.save(output, format="PNG")
                        image_data = output.getvalue()
                    return base64.b64encode(image_data).decode("utf-8")
            except Exception as e:
                logger.error(e)
                self.show_toast(_("Cannot open image"), self.main_overlay)
        elif file_type in ('plain_text', 'code', 'youtube', 'website'):
            with open(file_path, 'r', encoding="utf-8") as f:
                return f.read()
        elif file_type in ('pdf', 'docx', 'pptx', 'xlsx'):
            return self.mid.convert(file_path).text_content
        elif file_type == 'odt':
            doc = odfopen.load(file_path)
            markdown_elements = []
            for child in doc.text.childNodes:
                if child.qname[1] == 'p' or child.qname[1] == 'span':
                    markdown_elements.append(str(child))
                elif child.qname[1] == 'h':
                    markdown_elements.append('# {}'.format(str(child)))
                elif child.qname[1] == 'table':
                    generated_table = []
                    column_sizes = []
                    for row in child.getElementsByType(odftable.TableRow):
                        generated_table.append([])
                        for column_n, cell in enumerate(row.getElementsByType(odftable.TableCell)):
                            if column_n + 1 > len(column_sizes):
                                column_sizes.append(0)
                            if len(str(cell)) > column_sizes[column_n]:
                                column_sizes[column_n] = len(str(cell))
                            generated_table[-1].append(str(cell))
                    generated_table.insert(1, [])
                    for column_n in range(len(generated_table[0])):
                        generated_table[1].append('-' * column_sizes[column_n])
                    table_str = ''
                    for row in generated_table:
                        for column_n, cell in enumerate(row):
                            table_str += '| {} '.format(cell.ljust(column_sizes[column_n], ' '))
                        table_str += '|\n'
                    markdown_elements.append(table_str)
            return '\n\n'.join(markdown_elements)

    def remove_attached_file(self, name):
        logger.debug("Removing attached file")
        button = self.attachments[name]['button']
        button.get_parent().remove(button)
        del self.attachments[name]
        if len(self.attachments) == 0:
            self.attachment_box.set_visible(False)

    def attach_file(self, file_path, file_type):
        logger.debug(f"Attaching file: {file_path}")
        file_name = self.generate_numbered_name(os.path.basename(file_path), self.attachments.keys())
        content = self.get_content_of_file(file_path, file_type)
        if content:
            button_content = Adw.ButtonContent(
                label=file_name,
                icon_name={
                    "image": "image-x-generic-symbolic",
                    "code": "code-symbolic",
                    "youtube": "play-symbolic",
                    "website": "globe-symbolic"
                }.get(file_type, "document-text-symbolic")
            )
            button = Gtk.Button(
                vexpand=True,
                valign=0,
                name=file_name,
                css_classes=["flat"],
                tooltip_text=file_name,
                child=button_content
            )
            self.attachments[file_name] = {"path": file_path, "type": file_type, "content": content, "button": button}
            button.connect("clicked", lambda button : self.preview_file(file_name, content, file_type, True, self))
            self.attachment_container.append(button)
            self.attachment_box.set_visible(True)

    def chat_actions(self, action, user_data):
        chat_row = self.selected_chat_row
        chat_name = chat_row.label.get_label()
        action_name = action.get_name()
        if action_name in ('delete_chat', 'delete_current_chat'):
            dialog_widget.simple(
                _('Delete Chat?'),
                _("Are you sure you want to delete '{}'?").format(chat_name),
                lambda chat_name=chat_name, *_: self.chat_list_box.delete_chat(chat_name),
                _('Delete'),
                'destructive'
            )
        elif action_name in ('duplicate_chat', 'duplicate_current_chat'):
            self.chat_list_box.duplicate_chat(chat_name)
        elif action_name in ('rename_chat', 'rename_current_chat'):
            dialog_widget.simple_entry(
                _('Rename Chat?'),
                _("Renaming '{}'").format(chat_name),
                lambda new_chat_name, old_chat_name=chat_name, *_: self.chat_list_box.rename_chat(old_chat_name, new_chat_name),
                {'placeholder': _('Chat name'), 'default': True, 'text': chat_name},
                _('Rename')
            )
        elif action_name in ('export_chat', 'export_current_chat'):
            chat = self.chat_list_box.get_chat_by_name(chat_name)
            options = {
                _("Importable (.db)"): chat.export_db,
                _("Markdown"): lambda chat=chat: chat.export_md(False),
                _("Markdown (Obsidian Style)"): lambda chat=chat: chat.export_md(True),
                _("JSON"): lambda chat=chat: chat.export_json(False),
                _("JSON (Include Metadata)"): lambda chat=chat: chat.export_json(True)
            }
            dialog_widget.simple_dropdown(
                _("Export Chat"),
                _("Select a method to export the chat"),
                lambda option, options=options: options[option](),
                options.keys()
            )

    def current_chat_actions(self, action, user_data):
        self.selected_chat_row = self.chat_list_box.get_selected_row()
        self.chat_actions(action, user_data)

    def youtube_detected(self, video_url):
        try:
            response = requests.get('https://noembed.com/embed?url={}'.format(video_url))
            data = json.loads(response.text)

            transcriptions = generic_actions.get_youtube_transcripts(data['url'].split('=')[1])
            if len(transcriptions) == 0:
                GLib.idle_add(self.show_toast, _("This video does not have any transcriptions"), self.main_overlay)
                return

            if not any(filter(lambda x: '(en' in x and 'auto-generated' not in x and len(transcriptions) > 1, transcriptions)):
                transcriptions.insert(1, 'English (translate:en)')

            GLib.idle_add(dialog_widget.simple_dropdown,
                _('Attach YouTube Video?'),
                _('{}\n\nPlease select a transcript to include').format(data['title']),
                lambda caption_name, data=data, video_url=video_url: threading.Thread(target=generic_actions.attach_youtube, args=(data['title'], data['author_name'], data['url'], video_url, data['url'].split('=')[1], caption_name)).start(),
                transcriptions
            )
        except Exception as e:
            logger.error(e)
            GLib.idle_add(self.show_toast, _("Error attaching video, please try again"), self.main_overlay)
        GLib.idle_add(self.message_text_view_scrolled_window.set_sensitive, True)

    def cb_text_received(self, text):
        try:
            #Check if text is a Youtube URL
            youtube_regex = re.compile(
                r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/'
                r'(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})')
            url_regex = re.compile(
                r'http[s]?://'
                r'(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|'
                r'(?:%[0-9a-fA-F][0-9a-fA-F]))+'
                r'(?:\\:[0-9]{1,5})?'
                r'(?:/[^\\s]*)?'
            )
            if youtube_regex.match(text):
                self.message_text_view_scrolled_window.set_sensitive(False)
                threading.Thread(target=self.youtube_detected, args=(text,)).start()
            elif url_regex.match(text):
                dialog_widget.simple(
                    _('Attach Website? (Experimental)'),
                    _("Are you sure you want to attach\n'{}'?").format(text),
                    lambda url=text: threading.Thread(target=generic_actions.attach_website, args=(url,)).start()
                )
        except Exception as e:
            logger.error(e)

    def cb_image_received(self, clipboard, result):
        try:
            texture = clipboard.read_texture_finish(result)
            if texture:
                if model_manager_widget.get_selected_model().get_vision():
                    pixbuf = Gdk.pixbuf_get_from_texture(texture)
                    if not os.path.exists(os.path.join(cache_dir, AlpacaFolders.images_temp_ext)):
                        os.makedirs(os.path.join(cache_dir, AlpacaFolders.images_temp_ext))
                    image_name = self.generate_numbered_name('image.png', os.listdir(os.path.join(cache_dir, os.path.join(cache_dir, AlpacaFolders.images_temp_ext))))
                    pixbuf.savev(os.path.join(cache_dir, '{}/{}'.format(AlpacaFolders.images_temp_ext, image_name)), "png", [], [])
                    self.attach_file(os.path.join(cache_dir, '{}/{}'.format(AlpacaFolders.images_temp_ext, image_name)), 'image')
                else:
                    self.show_toast(_("Image recognition is only available on specific models"), self.main_overlay)
        except Exception as e:
            pass

    def on_file_drop(self, drop_target, value, x, y):
        files = value.get_files()
        for file in files:
            extension = os.path.splitext(file.get_path())[1][1:]
            if extension in ('png', 'jpeg', 'jpg', 'webp', 'gif'):
                if model_manager_widget.get_selected_model().get_vision():
                    self.attach_file(file.get_path(), 'image')
                else:
                    self.show_toast(_("Image recognition is only available on specific models"), self.main_overlay)
            elif extension in ('txt', 'md'):
                self.attach_file(file.get_path(), 'plain_text')
            elif extension in ("c", "h", "css", "html", "js", "ts", "py", "java", "json", "xml",
                                "asm", "nasm", "cs", "csx", "cpp", "cxx", "cp", "hxx", "inc", "csv",
                                "lsp", "lisp", "el", "emacs", "l", "cu", "dockerfile", "glsl", "g",
                                "lua", "php", "rb", "ru", "rs", "sql", "sh", "p8"):
                self.attach_file(file.get_path(), 'code')
            elif extension == 'pdf':
                self.attach_file(file.get_path(), 'pdf')
            elif extension == 'docx':
                self.attach_file(file.get_path(), 'docx')
            elif extension == 'pptx':
                self.attach_file(file.get_path(), 'pptx')
            elif extension == 'xlsx':
                self.attach_file(file.get_path(), 'xlsx')

    def prepare_quick_chat(self):
        self.quick_ask_save_button.set_sensitive(False)
        chat = chat_widget.chat(_('Quick Ask'), 'QA', True)
        chat.set_visible_child_name('welcome-screen')
        self.quick_ask_overlay.set_child(chat)

    def quick_chat(self, message:str, mode:int):
        if not message:
            return

        buffer = self.quick_ask_message_text_view.get_buffer()
        buffer.delete(buffer.get_start_iter(), buffer.get_end_iter())
        self.quick_ask.present()
        default_model = self.get_current_instance().get_default_model()
        current_model = None
        if default_model:
            current_model = self.convert_model_name(default_model, 1)
        if current_model is None:
            self.show_toast(_("Please select a model before chatting"), self.quick_ask_overlay)
            return
        chat = self.quick_ask_overlay.get_child()
        m_element = chat.add_message(self.generate_uuid(), datetime.now(), None, mode == 1)
        m_element.set_text(message)
        if mode in (0, 2):
            m_element_bot = chat.add_message(self.generate_uuid(), datetime.now(), current_model, False)
            m_element_bot.set_text()
            chat.busy = True
            if mode == 0:
                threading.Thread(target=self.get_current_instance().generate_message, args=(m_element_bot, current_model)).start()
            else:
                threading.Thread(target=self.get_current_instance().use_tools, args=(m_element_bot, current_model)).start()

    def get_current_instance(self):
        if self.instance_listbox.get_selected_row():
            return self.instance_listbox.get_selected_row().instance
        else:
            return instance_manager.empty()

    def prepare_alpaca(self):
        self.main_navigation_view.replace_with_tags(['chat'])
        # Notice
        if not self.sql_instance.get_preference('last_notice_seen') == self.notice_dialog.get_name():
            self.notice_dialog.present(self)

        #Chat History
        self.load_history()

        threading.Thread(target=tool_manager.update_available_tools).start()

        if self.get_application().args.new_chat:
            self.chat_list_box.new_chat(self.get_application().args.new_chat)

        self.powersaver_warning_switch.set_active(self.sql_instance.get_preference('powersaver_warning', True))
        self.powersaver_warning_switch.set_sensitive(True)
        self.background_switch.set_active(self.sql_instance.get_preference('run_on_background', False))
        self.background_switch.set_sensitive(True)
        self.mic_auto_send_switch.set_active(self.sql_instance.get_preference('mic_auto_send', False))
        self.mic_auto_send_switch.set_sensitive(True)
        self.zoom_spin.set_value(self.sql_instance.get_preference('zoom', 100))
        self.zoom_spin.set_sensitive(True)
        self.zoom_changed(self.zoom_spin, True)

        selected_mic_model = self.sql_instance.get_preference('mic_model', 'base')
        selected_index = 0
        string_list = Gtk.StringList()
        for i, (model, size) in enumerate(STT_MODELS.items()):
            if model == selected_mic_model:
                selected_index = i
            string_list.append('{} ({})'.format(model.title(), size))

        self.mic_model_combo.set_model(string_list)
        self.mic_model_combo.set_selected(selected_index)
        self.mic_model_combo.set_sensitive(True)

        selected_language = self.sql_instance.get_preference('mic_language', 'en')
        selected_index = 0
        string_list = Gtk.StringList()
        for i, lan in enumerate(SPEACH_RECOGNITION_LANGUAGES):
            if lan == selected_language:
                selected_index = i
            string_list.append('{} ({})'.format(icu.Locale(lan).getDisplayLanguage(icu.Locale(lan)).title(), lan))

        self.mic_language_combo.set_model(string_list)
        self.mic_language_combo.set_selected(selected_index)
        self.mic_language_combo.set_sensitive(True)

        selected_voice = self.sql_instance.get_preference('tts_voice', '')
        selected_index = 0
        string_list = Gtk.StringList()
        for i, (name, value) in enumerate(TTS_VOICES.items()):
            if value == selected_voice:
                selected_index = i
            string_list.append(name)

        self.tts_voice_combo.set_model(string_list)
        self.tts_voice_combo.set_selected(selected_index)
        self.tts_voice_combo.set_sensitive(True)

        instance_manager.update_instance_list()

        if self.get_application().args.ask or self.get_application().args.quick_ask:
            self.prepare_quick_chat()
            self.quick_chat(self.get_application().args.ask, 0)

    def open_button_menu(self, gesture, x, y, menu):
        button = gesture.get_widget()
        popover = Gtk.PopoverMenu(
            menu_model=menu,
            has_arrow=False,
            halign=1
        )
        position = Gdk.Rectangle()
        position.x = x
        position.y = y
        popover.set_parent(button.get_child())
        popover.set_pointing_to(position)
        popover.popup()

    def request_screenshot(self):
        bus = SessionBus()
        portal = bus.get("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
        subscription = None

        def on_response(sender, obj, iface, signal, *params):
            response = params[0]
            if response[0] == 0:
                uri = response[1].get("uri")
                generic_actions.attach_file(Gio.File.new_for_uri(uri))
            else:
                logger.error(f"Screenshot request failed with response: {response}\n{sender}\n{obj}\n{iface}\n{signal}")
                self.show_toast(_("Attachment failed, screenshot might be too big"), self.main_overlay)
            if subscription:
                subscription.disconnect()

        subscription = bus.subscribe(
            iface="org.freedesktop.portal.Request",
            signal="Response",
            signal_fired=on_response
        )

        portal.Screenshot("", {"interactive": Variant('b', True)})

    def check_for_metered_connection(self):
        try:
            proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SYSTEM,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.freedesktop.NetworkManager",
                "/org/freedesktop/NetworkManager",
                "org.freedesktop.NetworkManager",
                None
            )

            active_connections = proxy.get_cached_property("ActiveConnections").unpack()
            for path in active_connections:
                conn_proxy = Gio.DBusProxy.new_for_bus_sync(
                    Gio.BusType.SYSTEM,
                    Gio.DBusProxyFlags.NONE,
                    None,
                    "org.freedesktop.NetworkManager",
                    path,
                    "org.freedesktop.NetworkManager.Connection.Active",
                    None
                )

                devices = conn_proxy.get_cached_property("Devices").unpack()
                for device_path in devices:
                    device_proxy = Gio.DBusProxy.new_for_bus_sync(
                        Gio.BusType.SYSTEM,
                        Gio.DBusProxyFlags.NONE,
                        None,
                        "org.freedesktop.NetworkManager",
                        device_path,
                        "org.freedesktop.NetworkManager.Device",
                        None
                    )

                    metered = device_proxy.get_cached_property("Metered")
                    if metered is not None:
                        value = metered.unpack()
                        return value  # 0–3, same as explained before
            return None
        except Exception as e:
            print("Error checking metered state:", e)
            return None

    def attachment_request(self):
        ff = Gtk.FileFilter()
        ff.set_name(_('Any compatible Alpaca attachment'))
        file_filters = [ff]
        mimes = (
            'text/plain',
            'application/pdf',
            'application/vnd.oasis.opendocument.text',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        for mime in mimes:
            ff = Gtk.FileFilter()
            ff.add_mime_type(mime)
            file_filters[0].add_mime_type(mime)
            file_filters.append(ff)
        if model_manager_widget.get_selected_model().get_vision():
            file_filters[0].add_pixbuf_formats()
            file_filters.append(self.file_filter_image)
        dialog_widget.simple_file(file_filters, generic_actions.attach_file)

    def show_instance_manager(self):
        self.instance_preferences_page.set_sensitive(not any([tab.chat_window.busy for tab in self.chat_list_box.tab_list]))
        GLib.idle_add(self.main_navigation_view.push_by_tag, 'instance_manager')

    def toggle_searchbar(self):
        # TODO Gnome 48: Replace with get_visible_page_tag()
        current_tag = self.main_navigation_view.get_visible_page().get_tag()

        searchbars = {
            'chat': self.message_searchbar,
            'model_manager': self.model_searchbar
        }

        if searchbars.get(current_tag):
            searchbars.get(current_tag).set_search_mode(not searchbars.get(current_tag).get_search_mode())

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        GtkSource.init()
        message_widget.window = self
        chat_widget.window = self
        dialog_widget.window = self
        terminal_widget.window = self
        generic_actions.window = self
        model_manager_widget.window = self
        instance_manager.window = self
        tool_manager.window = self

        self.prepare_quick_chat()
        self.model_searchbar.connect_entry(self.searchentry_models)
        self.model_searchbar.connect('notify::search-mode-enabled', lambda *_: self.model_search_changed(self.searchentry_models))

        # Prepare model selector
        list(self.model_dropdown)[0].add_css_class('flat')
        self.model_dropdown.set_model(Gio.ListStore.new(model_manager_widget.local_model_row))
        self.model_dropdown.set_expression(Gtk.PropertyExpression.new(model_manager_widget.local_model_row, None, "name"))
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", lambda factory, list_item: list_item.set_child(Gtk.Label(ellipsize=2, xalign=0)))
        factory.connect("bind", lambda factory, list_item: list_item.get_child().set_text(list_item.get_item().name))
        self.model_dropdown.set_factory(factory)
        list(list(self.model_dropdown)[1].get_child())[1].set_propagate_natural_width(True)
        list(list(self.title_no_model_button.get_child())[0])[1].set_ellipsize(3)

        if sys.platform not in Platforms.ported:
            self.model_manager_stack.set_enable_transitions(True)

            # Logic to remember the window size upon application shutdown and
            # startup; will restore the state of the app after closing and
            # opening it again, especially useful for large, HiDPI displays.
            self.settings = Gio.Settings(schema_id="com.jeffser.Alpaca.State")

            # Please also see the GNOME developer documentation:
            # https://developer.gnome.org/documentation/tutorials/save-state.html
            for el in [
                ("width", "default-width"),
                ("height", "default-height"),
                ("is-maximized", "maximized")
            ]:
                self.settings.bind(
                    el[0],
                    self,
                    el[1],
                    Gio.SettingsBindFlags.DEFAULT
                )

        self.chat_list_box = chat_widget.chat_list()
        self.chat_list_container.set_child(self.chat_list_box)

        drop_target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop_target.connect('drop', self.on_file_drop)
        self.message_text_view = GtkSource.View(
            css_classes=['message_text_view'],
            top_margin=10,
            bottom_margin=10,
            hexpand=True,
            wrap_mode=3,
            valign=3,
            name="main_text_view"
        )

        self.message_text_view_scrolled_window.set_child(self.message_text_view)
        self.message_text_view.add_controller(drop_target)
        self.message_text_view.get_buffer().set_style_scheme(GtkSource.StyleSchemeManager.get_default().get_scheme('adwaita'))
        self.message_text_view.connect('paste-clipboard', self.on_clipboard_paste)

        self.quick_ask_message_text_view = GtkSource.View(
            css_classes=['message_text_view'],
            top_margin=10,
            bottom_margin=10,
            hexpand=True,
            wrap_mode=3,
            valign=3,
            name="quick_chat_text_view"
        )
        self.quick_ask_text_view_scrolled_window.set_child(self.quick_ask_message_text_view)
        self.quick_ask_message_text_view.get_buffer().set_style_scheme(GtkSource.StyleSchemeManager.get_default().get_scheme('adwaita'))

        def enter_key_handler(controller, keyval, keycode, state, text_view):
            if keyval==Gdk.KEY_Return and not (state & Gdk.ModifierType.SHIFT_MASK): # Enter pressed without shift
                mode = 0
                if state & Gdk.ModifierType.CONTROL_MASK: # Ctrl, send system message
                    mode = 1
                elif state & Gdk.ModifierType.ALT_MASK: # Alt, send tool message
                    mode = 2
                if text_view.get_name() == 'main_text_view':
                    self.send_message(None, mode)
                elif text_view.get_name() == 'quick_chat_text_view':
                    buffer = text_view.get_buffer()
                    self.quick_chat(buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False), mode)
                return True

        for text_view in (self.message_text_view, self.quick_ask_message_text_view):
            enter_key_controller = Gtk.EventControllerKey.new()
            enter_key_controller.connect("key-pressed", lambda c, kv, kc, stt, tv=text_view: enter_key_handler(c, kv, kc, stt, tv))
            text_view.add_controller(enter_key_controller)

        for name, data in {
            'send': {
                'button': self.action_button_stack.get_child_by_name('send'),
                'menu': self.send_message_menu
            },
            'attachment': {
                'button': self.attachment_button,
                'menu': self.attachment_menu
            }
        }.items():
            if name == 'attachment' and sys.platform not in Platforms.ported:
                data['menu'].append(_('Attach Screenshot'), 'app.attach_screenshot')
            gesture_click = Gtk.GestureClick(button=3)
            gesture_click.connect("released", lambda gesture, _n_press, x, y, menu=data.get('menu'): self.open_button_menu(gesture, x, y, menu))
            data.get('button').add_controller(gesture_click)
            gesture_long_press = Gtk.GestureLongPress()
            gesture_long_press.connect("pressed", lambda gesture, x, y, menu=data.get('menu'): self.open_button_menu(gesture, x, y, menu))
            data.get('button').add_controller(gesture_long_press)

        universal_actions = {
            'new_chat': [lambda *_: self.chat_list_box.new_chat(), ['<primary>n']],
            'import_chat': [lambda *_: self.chat_list_box.import_chat()],
            'duplicate_chat': [self.chat_actions],
            'duplicate_current_chat': [self.current_chat_actions],
            'delete_chat': [self.chat_actions],
            'delete_current_chat': [self.current_chat_actions, ['<primary>w']],
            'rename_chat': [self.chat_actions],
            'rename_current_chat': [self.current_chat_actions, ['F2']],
            'export_chat': [self.chat_actions],
            'export_current_chat': [self.current_chat_actions],
            'toggle_sidebar': [lambda *_: self.split_view_overlay.set_show_sidebar(not self.split_view_overlay.get_show_sidebar()), ['F9']],
            'toggle_search': [lambda *_: self.toggle_searchbar(), ['<primary>f']],
            'send_message': [lambda *_: self.send_message(None, 0)],
            'send_system_message': [lambda *_: self.send_message(None, 1)],
            'attach_file': [lambda *_: self.attachment_request()],
            'attach_screenshot': [lambda *i: self.request_screenshot() if model_manager_widget.get_selected_model().get_vision() else self.show_toast(_("Image recognition is only available on specific models"), self.main_overlay)],
            'attach_url': [lambda *i: dialog_widget.simple_entry(_('Attach Website? (Experimental)'), _('Please enter a website URL'), self.cb_text_received, {'placeholder': 'https://jeffser.com/alpaca/'})],
            'attach_youtube': [lambda *i: dialog_widget.simple_entry(_('Attach YouTube Captions?'), _('Please enter a YouTube video URL'), self.cb_text_received, {'placeholder': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'})],
            'model_manager' : [lambda *i: GLib.idle_add(self.main_navigation_view.push_by_tag, 'model_manager') if self.main_navigation_view.get_visible_page().get_tag() != 'model_manager' else GLib.idle_add(self.main_navigation_view.pop_to_tag, 'chat'), ['<primary>m']],
            'instance_manager' : [lambda *i: self.show_instance_manager() if self.main_navigation_view.get_visible_page().get_tag() != 'instance_manager' else GLib.idle_add(self.main_navigation_view.pop_to_tag, 'chat'), ['<primary>i']],
            'download_model_from_name' : [lambda *i: dialog_widget.simple_entry(_('Download Model?'), _('Please enter the model name following this template: name:tag'), lambda name: threading.Thread(target=model_manager_widget.pull_model_confirm, args=(name,)).start(), {'placeholder': 'deepseek-r1:7b'})],
            'reload_added_models': [lambda *_: model_manager_widget.update_local_model_list()],
            'delete_all_chats': [lambda *i: self.get_visible_dialog().close() and dialog_widget.simple(_('Delete All Chats?'), _('Are you sure you want to delete all chats?'), lambda: [GLib.idle_add(self.chat_list_box.delete_chat, c.chat_window.get_name()) for c in self.chat_list_box.tab_list], _('Delete'), 'destructive')],
            'use_tools': [lambda *_: self.send_message(None, 2)],
            'tool_manager': [lambda *i: GLib.idle_add(self.main_navigation_view.push_by_tag, 'tool_manager') if self.main_navigation_view.get_visible_page().get_tag() != 'tool_manager' else GLib.idle_add(self.main_navigation_view.pop_to_tag, 'chat'), ['<primary>t']],
            'start_quick_ask': [lambda *_: self.quick_ask.present(), ['<primary><alt>a']]
        }
        for action_name, data in universal_actions.items():
            self.get_application().create_action(action_name, data[0], data[1] if len(data) > 1 else None)

        if sys.platform in Platforms.ported:
            self.get_application().lookup_action('attach_screenshot').set_enabled(False)

        self.file_preview_remove_button.connect('clicked', lambda button: self.get_visible_dialog().close() and dialog_widget.simple(_('Remove Attachment?'), _("Are you sure you want to remove attachment?"), lambda button=button: self.remove_attached_file(button.get_name()), _('Remove'), 'destructive'))
        self.model_creator_name.get_delegate().connect("insert-text", lambda *_: self.check_alphanumeric(*_, ['-', '.', '_', ' ']))
        self.model_creator_tag.get_delegate().connect("insert-text", lambda *_: self.check_alphanumeric(*_, ['-', '.', '_', ' ']))

        checker = Spelling.Checker.get_default()
        adapter = Spelling.TextBufferAdapter.new(self.message_text_view.get_buffer(), checker)
        self.message_text_view.set_extra_menu(adapter.get_menu_model())
        self.message_text_view.insert_action_group('spelling', adapter)
        adapter.set_enabled(True)
        self.set_focus(self.message_text_view)
            
        Gio.PowerProfileMonitor.dup_default().connect("notify::power-saver-enabled", lambda monitor, *_: self.banner.set_revealed(monitor.get_power_saver_enabled() and self.powersaver_warning_switch.get_active() and self.get_current_instance().instance_type == 'ollama:managed'))
        self.banner.connect('button-clicked', lambda *_: self.banner.set_revealed(False))

        if shutil.which('ollama'):
            text = _('Already Installed!')
            self.install_ollama_button.set_label(text)
            self.install_ollama_button.set_tooltip_text(text)
            self.install_ollama_button.set_sensitive(False)

        if self.sql_instance.get_preference('skip_welcome_page', False):
            self.prepare_alpaca()
        else:
            self.main_navigation_view.replace_with_tags(['welcome'])

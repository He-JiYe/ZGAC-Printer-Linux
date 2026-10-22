"""Optional GTK tray helper. Only fixed UI actions cross its stdout pipe."""
import sys

MENU_ACTIONS = [('打开','show'), ('设置','settings'), ('注销','logout'), ('退出','quit')]


def main():
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        gi.require_version('AyatanaAppIndicator3', '0.1')
        from gi.repository import Gtk, GLib, AyatanaAppIndicator3 as Indicator
        if not Gtk.init_check()[0]:
            return 1
        indicator = Indicator.Indicator.new('org.zgcaprint.Client', 'printer', Indicator.IndicatorCategory.APPLICATION_STATUS)
        menu = Gtk.Menu()
        def action(_, command):
            try:
                print(command, flush=True)
            except BrokenPipeError:
                Gtk.main_quit()
        for label, command in MENU_ACTIONS:
            item = Gtk.MenuItem(label=label)
            item.connect('activate', action, command)
            menu.append(item)
        menu.show_all()
        indicator.set_menu(menu)
        indicator.set_status(Indicator.IndicatorStatus.ACTIVE)
        GLib.io_add_watch(sys.stdin, GLib.IO_HUP, lambda *_: Gtk.main_quit())
        print('ready', flush=True)
        Gtk.main()
        return 0
    except (ImportError, ValueError):
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

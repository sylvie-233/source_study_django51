import functools
import os
import pkgutil
import sys
from argparse import (
    _AppendConstAction,
    _CountAction,
    _StoreConstAction,
    _SubParsersAction,
)
from collections import defaultdict
from difflib import get_close_matches
from importlib import import_module

import django
from django.apps import apps
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import (
    BaseCommand,
    CommandError,
    CommandParser,
    handle_default_options,
)
from django.core.management.color import color_style
from django.utils import autoreload


# 从目录下的commands子目录查找 命令.py  文件（每个命令脚本中都必有一个Command类）（返回命令名称）
def find_commands(management_dir):
    """
    Given a path to a management directory, return a list of all the command
    names that are available.
    """
    command_dir = os.path.join(management_dir, "commands")
    return [
        name
        for _, name, is_pkg in pkgutil.iter_modules([command_dir])
        if not is_pkg and not name.startswith("_")
    ]

# 加载命令脚本的Command类（app_name包名、name脚本名称）$app_name.management.commands.$name
# 每个命令脚本中，必有一个Command类
def load_command_class(app_name, name):
    """
    Given a command name and an application name, return the Command
    class instance. Allow all errors raised by the import process
    (ImportError, AttributeError) to propagate.
    """
    module = import_module("%s.management.commands.%s" % (app_name, name))
    return module.Command()

# dict { key(命令名) : value(django.core|app名称（app包名）) }
# 获取所有的命令脚本（默认脚本（django.core.management.commands）以及每个app下的commands目录）
@functools.cache
def get_commands():
    """
    Return a dictionary mapping command names to their callback applications.

    Look for a management.commands package in django.core, and in each
    installed application -- if a commands package exists, register all
    commands in that package.

    Core commands are always included. If a settings module has been
    specified, also include user-defined commands.

    The dictionary is in the format {command_name: app_name}. Key-value
    pairs from this dictionary can then be used in calls to
    load_command_class(app_name, command_name)

    The dictionary is cached on the first call and reused on subsequent
    calls.
    """

    # 加载核心（django.core）Command
    commands = {name: "django.core" for name in find_commands(__path__[0])}

    if not settings.configured:
        return commands

    # 加载每个app下的command
    for app_config in reversed(apps.get_app_configs()):
        # path = os.path.join(app_config.path, "management")
        commands.update({name: app_config.name for name in find_commands(path)})

    return commands

# 调用命令执行（可传入Command类和命令字符串）
def call_command(command_name, *args, **options):
    """
    Call the given command, with the given options and args/kwargs.

    This is the primary API you should use for calling specific commands.

    `command_name` may be a string or a command object. Using a string is
    preferred unless the command object is required for further processing or
    testing.

    Some examples:
        call_command('migrate')
        call_command('shell', plain=True)
        call_command('sqlmigrate', 'myapp')

        from django.core.management.commands import flush
        cmd = flush.Command()
        call_command(cmd, verbosity=0, interactive=False)
        # Do something with cmd ...
    """
    # 传入的为命令类
    if isinstance(command_name, BaseCommand):
        # Command object passed in.
        command = command_name
        # command_name为命令名称
        command_name = command.__class__.__module__.split(".")[-1]
    # 传入的为字符串
    else:
        # Load the command object by name.
        try:
            # 根据命令名称获取包名
            app_name = get_commands()[command_name]
        except KeyError:
            # 没有该命令则报错
            raise CommandError("Unknown command: %r" % command_name)

        # dict中存入的为Command类
        if isinstance(app_name, BaseCommand):
            # If the command is already loaded, use it directly.
            command = app_name
        else:
            command = load_command_class(app_name, command_name)

    # 创建命令参数解析器
    # Simulate argument parsing to get the option defaults (see #10080 for details).
    parser = command.create_parser("", command_name)
    # Use the `dest` option name from the parser option
    opt_mapping = {
        min(s_opt.option_strings).lstrip("-").replace("-", "_"): s_opt.dest
        for s_opt in parser._actions
        if s_opt.option_strings
    }
    arg_options = {opt_mapping.get(key, key): value for key, value in options.items()}
    parse_args = []
    for arg in args:
        if isinstance(arg, (list, tuple)):
            parse_args += map(str, arg)
        else:
            parse_args.append(str(arg))

    # 递归获取命令解析器参数
    def get_actions(parser):
        # Parser actions and actions from sub-parser choices.
        for opt in parser._actions:
            if isinstance(opt, _SubParsersAction):
                for sub_opt in opt.choices.values():
                    yield from get_actions(sub_opt)
            else:
                yield opt


    parser_actions = list(get_actions(parser))
    mutually_exclusive_required_options = {
        opt
        for group in parser._mutually_exclusive_groups
        for opt in group._group_actions
        if group.required
    }
    # Any required arguments which are passed in via **options must be passed
    # to parse_args().
    for opt in parser_actions:
        if opt.dest in options and (
            opt.required or opt in mutually_exclusive_required_options
        ):
            opt_dest_count = sum(v == opt.dest for v in opt_mapping.values())
            # 命令选项设置重复
            if opt_dest_count > 1:
                raise TypeError(
                    f"Cannot pass the dest {opt.dest!r} that matches multiple "
                    f"arguments via **options."
                )
            parse_args.append(min(opt.option_strings))
            if isinstance(opt, (_AppendConstAction, _CountAction, _StoreConstAction)):
                continue
            value = arg_options[opt.dest]
            if isinstance(value, (list, tuple)):
                parse_args += map(str, value)
            else:
                parse_args.append(str(value))
    defaults = parser.parse_args(args=parse_args)
    # 合并命令选项
    defaults = dict(defaults._get_kwargs(), **arg_options)
    # Raise an error if any unknown options were passed.
    stealth_options = set(command.base_stealth_options + command.stealth_options)
    dest_parameters = {action.dest for action in parser_actions}
    valid_options = (dest_parameters | stealth_options).union(opt_mapping)
    unknown_options = set(options) - valid_options
    if unknown_options:
        raise TypeError(
            "Unknown option(s) for %s command: %s. "
            "Valid options are: %s."
            % (
                command_name,
                ", ".join(sorted(unknown_options)),
                ", ".join(sorted(valid_options)),
            )
        )
    # Move positional args out of options to mimic legacy optparse
    args = defaults.pop("args", ())
    if "skip_checks" not in options:
        defaults["skip_checks"] = True

    # 命令execute执行调用
    return command.execute(*args, **defaults)


# 命令工具集类
class ManagementUtility:
    """
    Encapsulate the logic of the django-admin and manage.py utilities.
    """

    def __init__(self, argv=None):
        # 初始化传入参数，或者使用命令参数
        self.argv = argv or sys.argv[:]
        # 执行程序名
        self.prog_name = os.path.basename(self.argv[0])
        if self.prog_name == "__main__.py":
            self.prog_name = "python -m django"
        self.settings_exception = None

    # 获取命令帮助信息（返回字符串）
    def main_help_text(self, commands_only=False):
        """Return the script's main help text, as a string."""
        if commands_only:
            usage = sorted(get_commands())
        else:
            usage = [
                "",
                "Type '%s help <subcommand>' for help on a specific subcommand."
                % self.prog_name,
                "",
                "Available subcommands:",
            ]
            commands_dict = defaultdict(lambda: [])
            for name, app in get_commands().items():
                if app == "django.core":
                    app = "django"
                else:
                    app = app.rpartition(".")[-1]
                commands_dict[app].append(name)
            style = color_style()
            for app in sorted(commands_dict):
                usage.append("")
                usage.append(style.NOTICE("[%s]" % app))
                for name in sorted(commands_dict[app]):
                    usage.append("    %s" % name)
            # Output an extra note if settings are not properly configured
            if self.settings_exception is not None:
                usage.append(
                    style.NOTICE(
                        "Note that only Django core commands are listed "
                        "as settings are not properly configured (error: %s)."
                        % self.settings_exception
                    )
                )

        return "\n".join(usage)

    # 子命令Command执行
    def fetch_command(self, subcommand):
        """
        Try to fetch the given subcommand, printing a message with the
        appropriate command called from the command line (usually
        "django-admin" or "manage.py") if it can't be found.
        """
        # Get commands outside of try block to prevent swallowing exceptions
        commands = get_commands()
        try:
            app_name = commands[subcommand]
        except KeyError:
            if os.environ.get("DJANGO_SETTINGS_MODULE"):
                # If `subcommand` is missing due to misconfigured settings, the
                # following line will retrigger an ImproperlyConfigured exception
                # (get_commands() swallows the original one) so the user is
                # informed about it.
                settings.INSTALLED_APPS
            elif not settings.configured:
                sys.stderr.write("No Django settings specified.\n")
            possible_matches = get_close_matches(subcommand, commands)
            sys.stderr.write("Unknown command: %r" % subcommand)
            if possible_matches:
                sys.stderr.write(". Did you mean %s?" % possible_matches[0])
            sys.stderr.write("\nType '%s help' for usage.\n" % self.prog_name)
            sys.exit(1)
        if isinstance(app_name, BaseCommand):
            # If the command is already loaded, use it directly.
            klass = app_name
        else:
            klass = load_command_class(app_name, subcommand)

        # 返回Command类
        return klass

    def autocomplete(self):
        """
        Output completion suggestions for BASH.

        The output of this function is passed to BASH's `COMPREPLY` variable
        and treated as completion suggestions. `COMPREPLY` expects a space
        separated string as the result.

        The `COMP_WORDS` and `COMP_CWORD` BASH environment variables are used
        to get information about the cli input. Please refer to the BASH
        man-page for more information about this variables.

        Subcommand options are saved as pairs. A pair consists of
        the long option string (e.g. '--exclude') and a boolean
        value indicating if the option requires arguments. When printing to
        stdout, an equal sign is appended to options which require arguments.

        Note: If debugging this function, it is recommended to write the debug
        output in a separate file. Otherwise the debug output will be treated
        and formatted as potential completion suggestions.
        """
        # Don't complete if user hasn't sourced bash_completion file.
        if "DJANGO_AUTO_COMPLETE" not in os.environ:
            return

        cwords = os.environ["COMP_WORDS"].split()[1:]
        cword = int(os.environ["COMP_CWORD"])

        try:
            curr = cwords[cword - 1]
        except IndexError:
            curr = ""

        subcommands = [*get_commands(), "help"]
        options = [("--help", False)]

        # subcommand
        if cword == 1:
            print(" ".join(sorted(filter(lambda x: x.startswith(curr), subcommands))))
        # subcommand options
        # special case: the 'help' subcommand has no options
        elif cwords[0] in subcommands and cwords[0] != "help":
            subcommand_cls = self.fetch_command(cwords[0])
            # special case: add the names of installed apps to options
            if cwords[0] in ("dumpdata", "sqlmigrate", "sqlsequencereset", "test"):
                try:
                    app_configs = apps.get_app_configs()
                    # Get the last part of the dotted path as the app name.
                    options.extend((app_config.label, 0) for app_config in app_configs)
                except ImportError:
                    # Fail silently if DJANGO_SETTINGS_MODULE isn't set. The
                    # user will find out once they execute the command.
                    pass
            parser = subcommand_cls.create_parser("", cwords[0])
            options.extend(
                (min(s_opt.option_strings), s_opt.nargs != 0)
                for s_opt in parser._actions
                if s_opt.option_strings
            )
            # filter out previously specified options from available options
            prev_opts = {x.split("=")[0] for x in cwords[1 : cword - 1]}
            options = (opt for opt in options if opt[0] not in prev_opts)

            # filter options by current input
            options = sorted((k, v) for k, v in options if k.startswith(curr))
            for opt_label, require_arg in options:
                # append '=' to options which require args
                if require_arg:
                    opt_label += "="
                print(opt_label)
        # Exit code of the bash completion function is never passed back to
        # the user, so it's safe to always exit with 0.
        # For more details see #25420.
        sys.exit(0)

    # django-admin执行入口（命令执行）
    def execute(self):
        """
        Given the command-line arguments, figure out which subcommand is being
        run, create a parser appropriate to that command, and run it.
        """
        # 获取子命令：
        try:
            subcommand = self.argv[1]
        except IndexError:
            subcommand = "help"  # Display help if no arguments were given.

        # Preprocess options to extract --settings and --pythonpath.
        # These options could affect the commands that are available, so they
        # must be processed early.
        parser = CommandParser(
            prog=self.prog_name,
            usage="%(prog)s subcommand [options] [args]",
            add_help=False,
            allow_abbrev=False,
        )
        # 指定配置文件
        parser.add_argument("--settings")
        # 指定python包搜索路径
        parser.add_argument("--pythonpath")
        # 其它参数保存在args中
        parser.add_argument("args", nargs="*")  # catch-all
        try:
            options, args = parser.parse_known_args(self.argv[2:])
            handle_default_options(options)
        except CommandError:
            pass  # Ignore any option errors at this point.

        try:
            settings.INSTALLED_APPS # LazySettings
        except ImproperlyConfigured as exc:
            self.settings_exception = exc
        except ImportError as exc:
            self.settings_exception = exc

        # runserver命令执行（django.setup()安装app）
        if settings.configured:
            # Start the auto-reloading dev server even if the code is broken.
            # The hardcoded condition is a code smell but we can't rely on a
            # flag on the command class because we haven't located it yet.
            if subcommand == "runserver" and "--noreload" not in self.argv:
                try:
                    # 异常处理，并调用django.setup()函数开始运行
                    autoreload.check_errors(django.setup)()
                except Exception:
                    # The exception will be raised later in the child process
                    # started by the autoreloader. Pretend it didn't happen by
                    # loading an empty list of applications.
                    apps.all_models = defaultdict(dict)
                    apps.app_configs = {}
                    apps.apps_ready = apps.models_ready = apps.ready = True

                    # Remove options not compatible with the built-in runserver
                    # (e.g. options for the contrib.staticfiles' runserver).
                    # Changes here require manually testing as described in
                    # #27522.
                    _parser = self.fetch_command("runserver").create_parser(
                        "django", "runserver"
                    )
                    _options, _args = _parser.parse_known_args(self.argv[2:])
                    for _arg in _args:
                        self.argv.remove(_arg)

            # In all other cases, django.setup() is required to succeed.
            else:
                django.setup()

        self.autocomplete()

        # help命令执行
        if subcommand == "help":
            if "--commands" in args:
                sys.stdout.write(self.main_help_text(commands_only=True) + "\n")
            elif not options.args:
                sys.stdout.write(self.main_help_text() + "\n")
            else:
                self.fetch_command(options.args[0]).print_help(
                    self.prog_name, options.args[0]
                )
        # Special-cases: We want 'django-admin --version' and
        # 'django-admin --help' to work, for backwards compatibility.
        elif subcommand == "version" or self.argv[1:] == ["--version"]:
            sys.stdout.write(django.get_version() + "\n")
        elif self.argv[1:] in (["--help"], ["-h"]):
            sys.stdout.write(self.main_help_text() + "\n")
        else:
            self.fetch_command(subcommand).run_from_argv(self.argv)


# django-admin命令执行人口函数
def execute_from_command_line(argv=None):
    """Run a ManagementUtility."""
    utility = ManagementUtility(argv)
    utility.execute()

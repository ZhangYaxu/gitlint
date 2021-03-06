import os

try:
    # python 2.x
    from StringIO import StringIO
except ImportError:
    # python 3.x
    from io import StringIO

from click.testing import CliRunner
from mock import patch
from sh import CommandNotFound

from gitlint.tests.base import BaseTestCase
from gitlint import cli
from gitlint import hooks
from gitlint import __version__
from gitlint import config


class CLITests(BaseTestCase):
    USAGE_ERROR_CODE = 253
    GIT_CONTEXT_ERROR_CODE = 254
    CONFIG_ERROR_CODE = 255

    def setUp(self):
        self.cli = CliRunner()

    def test_version(self):
        result = self.cli.invoke(cli.cli, ["--version"])
        self.assertEqual(result.output.split("\n")[0], "cli, version {0}".format(__version__))

    @patch('gitlint.git.sh')
    @patch('gitlint.cli.sys')
    def test_lint(self, sys, sh):
        sys.stdin.isatty.return_value = True

        def git_log_side_effect(*args, **_kwargs):
            return_values = {'--pretty=%B': "commit-title\n\ncommit-body", '--pretty=%aN': "test author",
                             '--pretty=%aE': "test-email@foo.com", '--pretty=%ai': "2016-12-03 15:28:15 01:00",
                             '--pretty=%P': "abc"}
            return return_values[args[1]]

        sh.git.log.side_effect = git_log_side_effect
        sh.git.return_value = "file1.txt\npath/to/file2.txt\n"

        with patch('gitlint.display.stderr', new=StringIO()) as stderr:
            result = self.cli.invoke(cli.cli)
            self.assertEqual(stderr.getvalue(), '3: B5 Body message is too short (11<20): "commit-body"\n')
            self.assertEqual(result.exit_code, 1)

    def test_input_stream(self):
        expected_output = "1: T2 Title has trailing whitespace: \"WIP: title \"\n" + \
                          "1: T5 Title contains the word 'WIP' (case-insensitive): \"WIP: title \"\n" + \
                          "3: B6 Body message is missing\n"

        with patch('gitlint.display.stderr', new=StringIO()) as stderr:
            result = self.cli.invoke(cli.cli, input='WIP: title \n')
            self.assertEqual(stderr.getvalue(), expected_output)
            self.assertEqual(result.exit_code, 3)
            self.assertEqual(result.output, "")

    def test_silent_mode(self):
        with patch('gitlint.display.stderr', new=StringIO()) as stderr:
            result = self.cli.invoke(cli.cli, ["--silent"], input='WIP: title \n')
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(result.exit_code, 3)
            self.assertEqual(result.output, "")

    def test_verbosity(self):
        # We only test -v and -vv, more testing is really not required here
        # -v
        with patch('gitlint.display.stderr', new=StringIO()) as stderr:
            result = self.cli.invoke(cli.cli, ["-v"], input='WIP: title \n')
            self.assertEqual(stderr.getvalue(), "1: T2\n1: T5\n3: B6\n")
            self.assertEqual(result.exit_code, 3)
            self.assertEqual(result.output, "")

        # -vv
        expected_output = "1: T2 Title has trailing whitespace\n" + \
                          "1: T5 Title contains the word 'WIP' (case-insensitive)\n" + \
                          "3: B6 Body message is missing\n"

        with patch('gitlint.display.stderr', new=StringIO()) as stderr:
            result = self.cli.invoke(cli.cli, ["-vv"], input='WIP: title \n')
            self.assertEqual(stderr.getvalue(), expected_output)
            self.assertEqual(result.exit_code, 3)
            self.assertEqual(result.output, "")

        # -vvvv: not supported -> should print a config error
        with patch('gitlint.display.stderr', new=StringIO()) as stderr:
            result = self.cli.invoke(cli.cli, ["-vvvv"], input='WIP: title \n')
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(result.exit_code, CLITests.CONFIG_ERROR_CODE)
            self.assertEqual(result.output, "Config Error: Option 'verbosity' must be set between 0 and 3\n")

    def test_debug(self):
        with patch('gitlint.display.stderr', new=StringIO()) as stderr:
            config_path = self.get_sample_path("config/gitlintconfig")
            result = self.cli.invoke(cli.cli, ["--config", config_path, "--debug"], input="WIP: test")
            expected = self.get_expected('debug_output1', {'config_path': config_path,
                                                           'target': os.path.abspath(os.getcwd())})
            self.assertEqual(result.output, expected)
            self.assertEqual(stderr.getvalue(), "1: T5\n3: B6\n")
            self.assertEqual(result.exit_code, 2)

    def test_extra_path(self):
        with patch('gitlint.display.stderr', new=StringIO()) as stderr:
            extra_path = self.get_sample_path("user_rules")
            result = self.cli.invoke(cli.cli, ["--extra-path", extra_path, "--debug"], input='Test title\n')
            expected_output = "1: TUC1 Commit violation 1: \"Content 1\"\n" + \
                              "3: B6 Body message is missing\n"
            self.assertEqual(stderr.getvalue(), expected_output)
            self.assertEqual(result.exit_code, 2)

    def test_config_file(self):
        with patch('gitlint.display.stderr', new=StringIO()) as stderr:
            config_path = self.get_sample_path("config/gitlintconfig")
            result = self.cli.invoke(cli.cli, ["--config", config_path], input="WIP: test")
            self.assertEqual(result.output, "")
            self.assertEqual(stderr.getvalue(), "1: T5\n3: B6\n")
            self.assertEqual(result.exit_code, 2)

    def test_config_file_negative(self):
        # Directory as config file
        config_path = self.get_sample_path("config")
        result = self.cli.invoke(cli.cli, ["--config", config_path])
        expected_string = "Error: Invalid value for \"-C\" / \"--config\": Path \"{0}\" is a directory.".format(
            config_path)
        self.assertEqual(result.output.split("\n")[2], expected_string)
        self.assertEqual(result.exit_code, self.USAGE_ERROR_CODE)

        # Non existing file
        config_path = self.get_sample_path("foo")
        result = self.cli.invoke(cli.cli, ["--config", config_path])
        expected_string = "Error: Invalid value for \"-C\" / \"--config\": Path \"{0}\" does not exist.".format(
            config_path)
        self.assertEqual(result.output.split("\n")[2], expected_string)
        self.assertEqual(result.exit_code, self.USAGE_ERROR_CODE)

        # Invalid config file
        config_path = self.get_sample_path("config/invalid-option-value")
        result = self.cli.invoke(cli.cli, ["--config", config_path])
        self.assertEqual(result.exit_code, self.CONFIG_ERROR_CODE)

    @patch('gitlint.cli.sys')
    def test_target(self, sys):
        sys.stdin.isatty.return_value = True
        result = self.cli.invoke(cli.cli, ["--target", "/tmp"])
        # We expect gitlint to tell us that /tmp is not a git repo (this proves that it takes the target parameter
        # into account).
        self.assertEqual(result.exit_code, self.GIT_CONTEXT_ERROR_CODE)
        expected_path = os.path.realpath("/tmp")
        self.assertEqual(result.output, "%s is not a git repository.\n" % expected_path)

    def test_target_negative(self):
        # try setting a non-existing target
        result = self.cli.invoke(cli.cli, ["--target", "/foo/bar"])
        self.assertEqual(result.exit_code, self.USAGE_ERROR_CODE)
        expected_msg = "Error: Invalid value for \"--target\": Directory \"/foo/bar\" does not exist."
        self.assertEqual(result.output.split("\n")[2], expected_msg)

        # try setting a file as target
        target_path = self.get_sample_path("config/gitlintconfig")
        result = self.cli.invoke(cli.cli, ["--target", target_path])
        self.assertEqual(result.exit_code, self.USAGE_ERROR_CODE)
        expected_msg = "Error: Invalid value for \"--target\": Directory \"{0}\" is a file.".format(target_path)
        self.assertEqual(result.output.split("\n")[2], expected_msg)

    def test_config_precedence(self):
        # TODO(jroovers): this test really only test verbosity, we need to do some refactoring to gitlint.cli
        # to more easily test everything
        # Test that the config precedence is followed:
        # 1. commandline convenience flags
        # 2. commandline -c flags
        # 3. config file
        # 4. default config
        input_text = "WIP\n\nThis is a test message\n"
        config_path = self.get_sample_path("config/gitlintconfig")

        # 1. commandline convenience flags
        with patch('gitlint.display.stderr', new=StringIO()) as stderr:
            result = self.cli.invoke(cli.cli, ["-vvv", "-c", "general.verbosity=2", "--config", config_path],
                                     input=input_text)
            self.assertEqual(result.output, "")
            self.assertEqual(stderr.getvalue(), "1: T5 Title contains the word 'WIP' (case-insensitive): \"WIP\"\n")

        # 2. commandline -c flags
        with patch('gitlint.display.stderr', new=StringIO()) as stderr:
            result = self.cli.invoke(cli.cli, ["-c", "general.verbosity=2", "--config", config_path], input=input_text)
            self.assertEqual(result.output, "")
            self.assertEqual(stderr.getvalue(), "1: T5 Title contains the word 'WIP' (case-insensitive)\n")

        # 3. config file
        with patch('gitlint.display.stderr', new=StringIO()) as stderr:
            result = self.cli.invoke(cli.cli, ["--config", config_path], input=input_text)
            self.assertEqual(result.output, "")
            self.assertEqual(stderr.getvalue(), "1: T5\n")

        # 4. default config
        with patch('gitlint.display.stderr', new=StringIO()) as stderr:
            result = self.cli.invoke(cli.cli, input=input_text)
            self.assertEqual(result.output, "")
            self.assertEqual(stderr.getvalue(), "1: T5 Title contains the word 'WIP' (case-insensitive): \"WIP\"\n")

    @patch('gitlint.config.LintConfigGenerator.generate_config')
    def test_generate_config(self, generate_config):
        result = self.cli.invoke(cli.cli, ["generate-config"], input="testfile\n")
        self.assertEqual(result.exit_code, 0)
        expected_msg = "Please specify a location for the sample gitlint config file [.gitlint]: testfile\n" + \
                       "Successfully generated {0}\n".format(os.path.abspath("testfile"))
        self.assertEqual(result.output, expected_msg)
        generate_config.assert_called_once_with(os.path.abspath("testfile"))

    def test_generate_config_negative(self):
        # Non-existing directory
        result = self.cli.invoke(cli.cli, ["generate-config"], input="/foo/bar")
        self.assertEqual(result.exit_code, self.USAGE_ERROR_CODE)
        expected_msg = "Please specify a location for the sample gitlint config file [.gitlint]: /foo/bar\n" + \
                       "Error: Directory '/foo' does not exist.\n"
        self.assertEqual(result.output, expected_msg)

        # Existing file
        sample_path = self.get_sample_path("config/gitlintconfig")
        result = self.cli.invoke(cli.cli, ["generate-config"], input=sample_path)
        self.assertEqual(result.exit_code, self.USAGE_ERROR_CODE)
        expected_msg = "Please specify a location for the sample gitlint " + \
                       "config file [.gitlint]: {0}\n".format(sample_path) + \
                       "Error: File \"{0}\" already exists.\n".format(sample_path)
        self.assertEqual(result.output, expected_msg)

    @patch('gitlint.git.sh')
    @patch('gitlint.cli.sys')
    def test_git_error(self, sys, sh):
        sys.stdin.isatty.return_value = True
        sh.git.log.side_effect = CommandNotFound("git")
        result = self.cli.invoke(cli.cli)
        self.assertEqual(result.exit_code, self.GIT_CONTEXT_ERROR_CODE)

    @patch('gitlint.hooks.GitHookInstaller.install_commit_msg_hook')
    def test_install_hook(self, install_hook):
        result = self.cli.invoke(cli.cli, ["install-hook"])
        expected_path = os.path.join(os.getcwd(), hooks.COMMIT_MSG_HOOK_DST_PATH)
        expected = "Successfully installed gitlint commit-msg hook in {0}\n".format(expected_path)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output, expected)
        expected_config = config.LintConfig()
        expected_config.target = os.path.abspath(os.getcwd())
        install_hook.assert_called_once_with(expected_config)

    @patch('gitlint.hooks.GitHookInstaller.install_commit_msg_hook')
    def test_install_hook_target(self, install_hook):
        # Specified target
        result = self.cli.invoke(cli.cli, ["--target", self.SAMPLES_DIR, "install-hook"])
        expected_path = os.path.realpath(os.path.join(self.SAMPLES_DIR, hooks.COMMIT_MSG_HOOK_DST_PATH))
        expected = "Successfully installed gitlint commit-msg hook in %s\n" % expected_path
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output, expected)

        expected_config = config.LintConfig()
        expected_config.target = self.SAMPLES_DIR
        install_hook.assert_called_once_with(expected_config)

    @patch('gitlint.hooks.GitHookInstaller.install_commit_msg_hook', side_effect=hooks.GitHookInstallerError("test"))
    def test_install_hook_negative(self, install_hook):
        result = self.cli.invoke(cli.cli, ["install-hook"])
        self.assertEqual(result.exit_code, self.GIT_CONTEXT_ERROR_CODE)
        self.assertEqual(result.output, "test\n")
        expected_config = config.LintConfig()
        expected_config.target = os.path.abspath(os.getcwd())
        install_hook.assert_called_once_with(expected_config)

    @patch('gitlint.hooks.GitHookInstaller.uninstall_commit_msg_hook')
    def test_uninstall_hook(self, uninstall_hook):
        result = self.cli.invoke(cli.cli, ["uninstall-hook"])
        expected_path = os.path.realpath(os.path.join(os.getcwd(), hooks.COMMIT_MSG_HOOK_DST_PATH))
        expected = "Successfully uninstalled gitlint commit-msg hook from {0}\n".format(expected_path)
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.output, expected)
        expected_config = config.LintConfig()
        expected_config.target = os.path.abspath(os.getcwd())
        uninstall_hook.assert_called_once_with(expected_config)

    @patch('gitlint.hooks.GitHookInstaller.uninstall_commit_msg_hook', side_effect=hooks.GitHookInstallerError("test"))
    def test_uninstall_hook_negative(self, uninstall_hook):
        result = self.cli.invoke(cli.cli, ["uninstall-hook"])
        self.assertEqual(result.exit_code, self.GIT_CONTEXT_ERROR_CODE)
        self.assertEqual(result.output, "test\n")
        expected_config = config.LintConfig()
        expected_config.target = os.path.abspath(os.getcwd())
        uninstall_hook.assert_called_once_with(expected_config)

"""Shared helpers for the plain-script tests in tools/impacts/.

Symlink creation can fail on Windows runners (no privilege, or not implemented). A test that cannot
create its symlink is reported as skipped. It is neither a failure nor a silent pass.
"""
import os


class SkipTest(Exception):
    """Raised by a test to report itself as skipped."""


def symlink(src, dst, **kwargs):
    """os.symlink, or SkipTest when the platform will not create the link."""
    try:
        os.symlink(src, dst, **kwargs)
    except (OSError, NotImplementedError):
        raise SkipTest("symlinks unavailable")


def run_tests(tests, show_pass=False):
    """Run (name, callable) pairs. Print failures and skips, then the summary line.

    Returns the exit code: 1 when any test failed, else 0.
    """
    passed = failed = skipped = 0
    for name, fn in tests:
        try:
            fn()
        except SkipTest:
            skipped += 1
            print("SKIP %s: symlinks unavailable" % name)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("FAIL %s: %r" % (name, exc))
        else:
            passed += 1
            if show_pass:
                print("PASS", name)
    print("%d passed, %d failed, %d skipped" % (passed, failed, skipped))
    return 1 if failed else 0

#!/usr/bin/env python3
"""
Validate test files for syntax errors and basic structure
"""

import ast
import sys
import os
from pathlib import Path

def validate_syntax(file_path):
    """Validate Python file syntax"""
    try:
        with open(file_path, 'r') as f:
            source = f.read()

        # Parse the AST to check for syntax errors
        ast.parse(source)
        return True, None
    except SyntaxError as e:
        return False, f"Syntax error: {e}"
    except Exception as e:
        return False, f"Error: {e}"

def validate_test_structure(file_path):
    """Validate test file structure"""
    with open(file_path, 'r') as f:
        source = f.read()

    tree = ast.parse(source)

    # Check for test classes
    test_classes = []
    test_functions = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if node.name.startswith('Test'):
                test_classes.append(node.name)
        elif isinstance(node, ast.FunctionDef):
            if node.name.startswith('test_'):
                test_functions.append(node.name)

    return test_classes, test_functions

def main():
    """Main validation function"""
    tests_dir = Path("tests")
    if not tests_dir.exists():
        print("No tests directory found")
        return 1

    test_files = list(tests_dir.glob("test_*.py"))

    if not test_files:
        print("No test files found")
        return 1

    print(f"Found {len(test_files)} test files:")
    print()

    all_valid = True

    for test_file in test_files:
        print(f"Validating {test_file.name}...", end=" ")

        # Check syntax
        is_valid, error = validate_syntax(test_file)
        if not is_valid:
            print(f"❌ {error}")
            all_valid = False
            continue

        # Check structure
        test_classes, test_functions = validate_test_structure(test_file)

        print(f"✅")
        print(f"  - Classes: {len(test_classes)} ({', '.join(test_classes[:3])}{'...' if len(test_classes) > 3 else ''})")
        print(f"  - Functions: {len(test_functions)}")

        # Show some examples
        if test_functions:
            print(f"  - Examples: {', '.join(test_functions[:3])}{'...' if len(test_functions) > 3 else ''}")
        print()

    # Summary
    if all_valid:
        print("🎉 All test files are syntactically valid!")

        # Count total tests
        total_functions = sum(
            len(validate_test_structure(f)[1])
            for f in test_files
            if validate_syntax(f)[0]
        )

        total_classes = sum(
            len(validate_test_structure(f)[0])
            for f in test_files
            if validate_syntax(f)[0]
        )

        print(f"📊 Summary:")
        print(f"   - Test files: {len(test_files)}")
        print(f"   - Test classes: {total_classes}")
        print(f"   - Test functions: {total_functions}")

        return 0
    else:
        print("❌ Some test files have issues")
        return 1

if __name__ == "__main__":
    sys.exit(main())
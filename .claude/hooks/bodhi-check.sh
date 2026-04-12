#!/bin/bash
# Bodhi DSL PostToolUse hook
# Runs after every Edit/Write/MultiEdit to catch missing @bodhi tags immediately.
# Claude Code passes tool info as JSON via stdin.

INPUT=$(cat)

# Extract the file path from tool input
FILE_PATH=$(python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.read())
except Exception:
    sys.exit(0)
fp = d.get('tool_input', {}).get('file_path', '')
print(fp)
" 2>/dev/null <<< "$INPUT")

# Skip if no file path extracted
[ -z "$FILE_PATH" ] && exit 0
[ ! -f "$FILE_PATH" ] && exit 0

# --- Check 1: Inline tag check for source code files ---
if [[ "$FILE_PATH" =~ \.(java|kt)$ ]]; then
    # Find public methods missing @bodhi.intent in Java/Kotlin files
    MISSING=$(python3 -c "
import re, sys

with open('$FILE_PATH', 'r') as f:
    content = f.read()
    lines = content.split('\n')

# Patterns to skip (getters, setters, toString, hashCode, equals, constructors, main)
SKIP_PATTERNS = [
    r'^\s*public\s+\w+\s+get[A-Z]',
    r'^\s*public\s+\w+\s+set[A-Z]',
    r'^\s*public\s+\w+\s+is[A-Z]',
    r'^\s*public\s+(String\s+)?toString\s*\(',
    r'^\s*public\s+(int\s+)?hashCode\s*\(',
    r'^\s*public\s+(boolean\s+)?equals\s*\(',
    r'^\s*public\s+static\s+void\s+main\s*\(',
    r'^\s*public\s+\w+\s*\(',  # constructor (no return type)
]

# Find public method declarations
METHOD_RE = re.compile(r'^\s*(?:@\w+\s+)*public\s+(?:static\s+)?(?:final\s+)?(?:synchronized\s+)?(?:<[^>]+>\s+)?\w+(?:<[^>]+>)?\s+(\w+)\s*\(')
CONSTRUCTOR_RE = re.compile(r'^\s*(?:@\w+\s+)*public\s+[A-Z]\w*\s*\(')

missing = []
for i, line in enumerate(lines):
    # Skip constructors
    if CONSTRUCTOR_RE.match(line):
        continue

    m = METHOD_RE.match(line)
    if not m:
        continue

    method_name = m.group(1)

    # Skip known trivial methods
    skip = False
    for pat in SKIP_PATTERNS:
        if re.match(pat, line):
            skip = True
            break
    if skip:
        continue

    # Look backwards for @bodhi.intent in the preceding doc comment
    found_intent = False
    j = i - 1
    while j >= 0:
        prev = lines[j].strip()
        if prev.startswith('*/') or prev.startswith('*') or prev.startswith('/**'):
            if '@bodhi.intent' in lines[j]:
                found_intent = True
                break
            if prev.startswith('/**'):
                break  # reached start of doc comment
            j -= 1
            continue
        elif prev.startswith('//'):
            if '@bodhi.intent' in lines[j]:
                found_intent = True
                break
            j -= 1
            continue
        elif prev.startswith('@'):
            j -= 1  # skip annotations
            continue
        else:
            break  # no doc comment found
        j -= 1

    if not found_intent:
        missing.append(f'  Line {i+1}: {method_name}()')

if missing:
    print('\n'.join(missing))
" 2>/dev/null)

    if [ -n "$MISSING" ]; then
        echo "⚠ Bodhi DSL: public methods missing @bodhi.intent in $(basename "$FILE_PATH"):"
        echo "$MISSING"
        echo ""
        echo "Add @bodhi.intent to each method's doc comment before continuing."
        exit 1
    fi

elif [[ "$FILE_PATH" =~ \.(py)$ ]]; then
    # Find public functions/methods missing @bodhi.intent in Python files
    MISSING=$(python3 -c "
import re, sys

with open('$FILE_PATH', 'r') as f:
    lines = f.readlines()

SKIP = {'__init__', '__str__', '__repr__', '__eq__', '__hash__', 'main', 'setup', 'teardown'}

missing = []
for i, line in enumerate(lines):
    # Match function/method definitions (not private _xxx)
    m = re.match(r'^(\s*)def\s+([a-zA-Z][a-zA-Z0-9_]*)\s*\(', line)
    if not m:
        continue

    indent = m.group(1)
    func_name = m.group(2)

    # Skip private/protected and known trivial methods
    if func_name.startswith('_') or func_name in SKIP:
        continue

    # Check if the docstring below contains @bodhi.intent
    found_intent = False
    j = i + 1
    while j < len(lines):
        stripped = lines[j].strip()
        if stripped == '':
            j += 1
            continue
        if stripped.startswith('\"\"\"') or stripped.startswith(\"'''\"):
            # Found docstring, scan it for @bodhi.intent
            k = j
            while k < len(lines):
                if '@bodhi.intent' in lines[k]:
                    found_intent = True
                    break
                if k > j and ('\"\"\"' in lines[k] or \"'''\" in lines[k]):
                    break
                k += 1
        break

    if not found_intent:
        missing.append(f'  Line {i+1}: {func_name}()')

if missing:
    print('\n'.join(missing))
" 2>/dev/null)

    if [ -n "$MISSING" ]; then
        echo "⚠ Bodhi DSL: public functions missing @bodhi.intent in $(basename "$FILE_PATH"):"
        echo "$MISSING"
        echo ""
        echo "Add @bodhi.intent to each function's docstring before continuing."
        exit 1
    fi

elif [[ "$FILE_PATH" =~ \.(ts|tsx|js|jsx)$ ]]; then
    # Find exported functions missing @bodhi.intent in TS/JS files
    MISSING=$(python3 -c "
import re, sys

with open('$FILE_PATH', 'r') as f:
    lines = f.readlines()

missing = []
for i, line in enumerate(lines):
    # Match exported function/method declarations
    m = re.match(r'^\s*export\s+(?:async\s+)?function\s+(\w+)\s*[\(<]', line)
    if not m:
        m = re.match(r'^\s*(?:public|async\s+public|public\s+async)\s+(\w+)\s*[\(<]', line)
    if not m:
        continue

    func_name = m.group(1)

    # Skip trivial
    if func_name in ('constructor', 'toString', 'toJSON'):
        continue
    if func_name.startswith('get') or func_name.startswith('set'):
        # Check if it's a simple getter/setter (single line or very short)
        pass  # keep checking for now

    # Look backwards for @bodhi.intent in JSDoc
    found_intent = False
    j = i - 1
    while j >= 0:
        prev = lines[j].strip()
        if prev.startswith('*/') or prev.startswith('*') or prev.startswith('/**'):
            if '@bodhi.intent' in lines[j]:
                found_intent = True
                break
            if prev.startswith('/**'):
                break
            j -= 1
            continue
        elif prev.startswith('//'):
            if '@bodhi.intent' in lines[j]:
                found_intent = True
                break
            j -= 1
            continue
        elif prev.startswith('@'):
            j -= 1
            continue
        else:
            break
        j -= 1

    if not found_intent:
        missing.append(f'  Line {i+1}: {func_name}()')

if missing:
    print('\n'.join(missing))
" 2>/dev/null)

    if [ -n "$MISSING" ]; then
        echo "⚠ Bodhi DSL: exported functions missing @bodhi.intent in $(basename "$FILE_PATH"):"
        echo "$MISSING"
        echo ""
        echo "Add @bodhi.intent to each function's JSDoc comment before continuing."
        exit 1
    fi

elif [[ "$FILE_PATH" =~ \.(go)$ ]]; then
    # Find exported functions missing @bodhi.intent in Go files
    MISSING=$(python3 -c "
import re, sys

with open('$FILE_PATH', 'r') as f:
    lines = f.readlines()

missing = []
for i, line in enumerate(lines):
    m = re.match(r'^func\s+(?:\(\w+\s+\*?\w+\)\s+)?([A-Z]\w*)\s*\(', line)
    if not m:
        continue

    func_name = m.group(1)

    # Skip trivial
    if func_name in ('String', 'Error', 'MarshalJSON', 'UnmarshalJSON'):
        continue

    # Look backwards for @bodhi.intent in line comments
    found_intent = False
    j = i - 1
    while j >= 0:
        prev = lines[j].strip()
        if prev.startswith('//'):
            if '@bodhi.intent' in lines[j]:
                found_intent = True
                break
            j -= 1
            continue
        else:
            break

    if not found_intent:
        missing.append(f'  Line {i+1}: {func_name}()')

if missing:
    print('\n'.join(missing))
" 2>/dev/null)

    if [ -n "$MISSING" ]; then
        echo "⚠ Bodhi DSL: exported functions missing @bodhi.intent in $(basename "$FILE_PATH"):"
        echo "$MISSING"
        echo ""
        echo "Add @bodhi.intent to each function's comment before continuing."
        exit 1
    fi
fi

# --- Check 2: Tag completeness — detect code patterns that need tags ---
if [[ "$FILE_PATH" =~ \.(java|kt|py|ts|tsx|js|jsx|go)$ ]]; then
    WARNINGS=$(python3 -c "
import re, sys

with open('$FILE_PATH', 'r') as f:
    content = f.read()
    lines = content.split('\n')

warnings = []

# --- Patterns that indicate DB writes ---
DB_WRITE_PATTERNS = [
    r'\b(?:save|insert|update|delete|remove|persist|merge|flush)\s*\(',
    r'\b(?:repository|repo|dao|mapper)\s*\.\s*(?:save|insert|update|delete|remove)',
    r'\bINSERT\s+INTO\b',
    r'\bUPDATE\s+\w+\s+SET\b',
    r'\bDELETE\s+FROM\b',
    r'\bcreate_all|drop_all|add_all|commit\b',
]

# --- Patterns that indicate remote calls ---
REMOTE_CALL_PATTERNS = [
    r'\b(?:restTemplate|httpClient|webClient|feignClient)\s*\.\s*(?:get|post|put|delete|exchange|send)',
    r'\bfetch\s*\(',
    r'\baxios\s*\.\s*(?:get|post|put|delete|patch)',
    r'\brequests\s*\.\s*(?:get|post|put|delete|patch)',
    r'\b(?:grpc|stub)\s*\.\s*\w+\s*\(',
    r'\bhttp\.(?:Get|Post|Put|Delete)\s*\(',
]

# --- Patterns that indicate event publishing ---
EVENT_PUBLISH_PATTERNS = [
    r'\b(?:kafkaTemplate|rabbitTemplate|jmsTemplate)\s*\.\s*(?:send|convertAndSend)',
    r'\beventPublisher\s*\.\s*publish',
    r'\b(?:emit|dispatch|publish|broadcast)\s*\(',
    r'\bproducer\s*\.\s*send\s*\(',
    r'\bchannel\s*\.\s*(?:send|publish)\s*\(',
]

def find_enclosing_method(line_idx):
    \"\"\"Walk backwards to find the method/function definition that encloses this line.\"\"\"
    for j in range(line_idx, -1, -1):
        l = lines[j]
        # Java/Kotlin
        if re.match(r'\s*(?:public|private|protected)\s+', l) and '(' in l:
            return j, l.strip()
        # Python
        if re.match(r'\s*def\s+\w+\s*\(', l):
            return j, l.strip()
        # Go
        if re.match(r'^func\s+', l):
            return j, l.strip()
        # TS/JS
        if re.match(r'\s*(?:export\s+)?(?:async\s+)?function\s+', l) or \
           re.match(r'\s*(?:public|async)\s+\w+\s*\(', l):
            return j, l.strip()
    return None, None

def get_doc_comment_tags(method_line_idx):
    \"\"\"Extract all @bodhi.* tags from the doc comment above a method.\"\"\"
    tags = set()
    j = method_line_idx - 1
    while j >= 0:
        prev = lines[j].strip()
        if prev.startswith('*/') or prev.startswith('*') or prev.startswith('/**') or prev.startswith('//') or prev.startswith('@'):
            for tag in re.findall(r'@bodhi\.(\w+)', lines[j]):
                tags.add(tag)
            if prev.startswith('/**') or (prev.startswith('//') and j > 0 and not lines[j-1].strip().startswith('//')):
                break
            j -= 1
            continue
        # Python: check docstring below the def line, not above
        break
    return tags

def get_python_docstring_tags(def_line_idx):
    \"\"\"Extract @bodhi.* tags from Python docstring below def line.\"\"\"
    tags = set()
    j = def_line_idx + 1
    while j < len(lines):
        stripped = lines[j].strip()
        if stripped == '':
            j += 1
            continue
        if stripped.startswith('\"\"\"') or stripped.startswith(\"'''\"):
            k = j
            while k < len(lines):
                for tag in re.findall(r'@bodhi\.(\w+)', lines[k]):
                    tags.add(tag)
                if k > j and ('\"\"\"' in lines[k] or \"'''\" in lines[k]):
                    break
                k += 1
            break
        break
    return tags

checked_methods = set()

def check_patterns(pattern_list, required_tag, description):
    for i, line in enumerate(lines):
        # Skip comments and strings (rough heuristic)
        stripped = line.strip()
        if stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('#'):
            continue

        for pat in pattern_list:
            if re.search(pat, line, re.IGNORECASE):
                method_line, method_sig = find_enclosing_method(i)
                if method_line is None:
                    continue

                key = (method_line, required_tag)
                if key in checked_methods:
                    continue
                checked_methods.add(key)

                # Get tags from doc comment
                tags = get_doc_comment_tags(method_line)
                if not tags:
                    tags = get_python_docstring_tags(method_line)

                if 'intent' not in tags:
                    continue  # Check 1 already catches missing intent

                if required_tag not in tags:
                    warnings.append(f'  Line {i+1}: {description} detected but @bodhi.{required_tag} missing')
                break

check_patterns(DB_WRITE_PATTERNS, 'writes', 'DB write')
check_patterns(REMOTE_CALL_PATTERNS, 'calls', 'Remote call')
check_patterns(EVENT_PUBLISH_PATTERNS, 'emits', 'Event publish')

if warnings:
    print('\n'.join(warnings))
" 2>/dev/null)

    if [ -n "$WARNINGS" ]; then
        echo "⚠ Bodhi DSL: incomplete tags in $(basename "$FILE_PATH"):"
        echo "$WARNINGS"
        echo ""
        echo "Add the missing @bodhi.* tags to match the code behavior."
        exit 1
    fi
fi

# --- Check 3: Entity file check for new ORM models ---
if [[ "$FILE_PATH" =~ \.(java|kt)$ ]]; then
    # Check if this file defines a JPA/ORM entity
    IS_ENTITY=$(python3 -c "
import sys
with open('$FILE_PATH', 'r') as f:
    content = f.read()
# Check for common entity annotations
if any(marker in content for marker in ['@Entity', '@Table', '@Document', '@Collection']):
    print('yes')
" 2>/dev/null)

    if [ "$IS_ENTITY" = "yes" ]; then
        PROJECT_ROOT=$(git -C "$(dirname "$FILE_PATH")" rev-parse --show-toplevel 2>/dev/null || pwd)
        BODHI_DIR="$PROJECT_ROOT/.bodhi/entities"

        # Extract entity/table name from the file
        ENTITY_NAME=$(python3 -c "
import re, sys
with open('$FILE_PATH', 'r') as f:
    content = f.read()
# Try @Table(name=...)
m = re.search(r'@Table\s*\(\s*name\s*=\s*[\"'\'']([\w]+)[\"'\'']\s*\)', content)
if m:
    print(m.group(1))
    sys.exit(0)
# Try @Document(collection=...)
m = re.search(r'@(?:Document|Collection)\s*\(\s*(?:collection\s*=\s*)?[\"'\'']([\w]+)[\"'\'']\s*\)', content)
if m:
    print(m.group(1))
    sys.exit(0)
# Fallback: class name to snake_case
m = re.search(r'class\s+(\w+)', content)
if m:
    name = m.group(1)
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
    print(re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower())
" 2>/dev/null)

        if [ -n "$ENTITY_NAME" ] && [ -d "$BODHI_DIR" ] || [ -d "$(dirname "$BODHI_DIR")" ]; then
            if [ ! -f "$BODHI_DIR/${ENTITY_NAME}.yaml" ] && [ ! -f "$BODHI_DIR/${ENTITY_NAME}.yml" ]; then
                echo "⚠ Bodhi DSL: Entity class detected but no entity definition found."
                echo "  File: $(basename "$FILE_PATH")"
                echo "  Expected: .bodhi/entities/${ENTITY_NAME}.yaml"
                echo ""
                echo "Create the entity YAML file with table schema, fields, indexes, and relations."
                exit 1
            fi
        fi
    fi

elif [[ "$FILE_PATH" =~ \.(py)$ ]]; then
    # Check for SQLAlchemy/Django/Tortoise ORM models
    IS_MODEL=$(python3 -c "
import sys
with open('$FILE_PATH', 'r') as f:
    content = f.read()
if any(marker in content for marker in [
    'db.Model', 'Base)', 'DeclarativeBase', 'models.Model',
    'class Meta:', '__tablename__', 'tortoise.models'
]):
    print('yes')
" 2>/dev/null)

    if [ "$IS_MODEL" = "yes" ]; then
        PROJECT_ROOT=$(git -C "$(dirname "$FILE_PATH")" rev-parse --show-toplevel 2>/dev/null || pwd)
        BODHI_DIR="$PROJECT_ROOT/.bodhi/entities"

        TABLE_NAME=$(python3 -c "
import re, sys
with open('$FILE_PATH', 'r') as f:
    content = f.read()
# Try __tablename__
m = re.search(r'__tablename__\s*=\s*[\"'\'']([\w]+)[\"'\'']\s*', content)
if m:
    print(m.group(1))
    sys.exit(0)
# Try class Meta: db_table
m = re.search(r'db_table\s*=\s*[\"'\'']([\w]+)[\"'\'']\s*', content)
if m:
    print(m.group(1))
    sys.exit(0)
# Fallback: class name to snake_case
m = re.search(r'class\s+(\w+)\s*\(', content)
if m:
    name = m.group(1)
    s1 = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
    print(re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1).lower())
" 2>/dev/null)

        if [ -n "$TABLE_NAME" ] && [ -d "$BODHI_DIR" ] || [ -d "$(dirname "$BODHI_DIR")" ]; then
            if [ ! -f "$BODHI_DIR/${TABLE_NAME}.yaml" ] && [ ! -f "$BODHI_DIR/${TABLE_NAME}.yml" ]; then
                echo "⚠ Bodhi DSL: ORM model detected but no entity definition found."
                echo "  File: $(basename "$FILE_PATH")"
                echo "  Expected: .bodhi/entities/${TABLE_NAME}.yaml"
                echo ""
                echo "Create the entity YAML file with table schema, fields, indexes, and relations."
                exit 1
            fi
        fi
    fi
fi

# --- Check 4: YAML validation (if .bodhi/ exists and bodhi CLI available) ---
if [[ "$FILE_PATH" =~ \.(java|py|go|ts|js|tsx|kt)$ ]] || [[ "$FILE_PATH" =~ /\.bodhi/ ]]; then
    PROJECT_ROOT=$(git -C "$(dirname "$FILE_PATH")" rev-parse --show-toplevel 2>/dev/null || pwd)

    if [ -d "$PROJECT_ROOT/.bodhi" ] && command -v bodhi &>/dev/null; then
        OUTPUT=$(bodhi validate "$PROJECT_ROOT" 2>&1)
        EXIT_CODE=$?

        if [ $EXIT_CODE -ne 0 ]; then
            echo "⚠ Bodhi DSL validation failed — fix before continuing:"
            echo "$OUTPUT"
            exit 1
        fi

        CHECK_OUTPUT=$(bodhi check "$PROJECT_ROOT" 2>&1)
        CHECK_EXIT=$?

        if [ $CHECK_EXIT -ne 0 ]; then
            echo "⚠ Bodhi DSL consistency check failed — inline tags and YAML are out of sync:"
            echo "$CHECK_OUTPUT"
            exit 1
        fi
    fi
fi

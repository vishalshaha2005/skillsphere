"""Seed question sets for technical assessments."""

import re

QUESTION_BANKS = {
    "Python": [
        ("Which collection preserves insertion order and allows duplicate values?", ["set", "list", "frozenset", "dict keys view"], 1, "Easy"),
        ("What does a Python function return when it has no return statement?", ["None", "False", "0", "An empty string"], 0, "Easy"),
        ("Which syntax creates a generator expression?", ["[x for x in items]", "{x for x in items}", "(x for x in items)", "{x: x for x in items}"], 2, "Easy"),
        ("What is the main purpose of a context manager?", ["Manage setup and cleanup around a block", "Compile a module", "Retry failed imports", "Create a thread"], 0, "Medium"),
        ("Which statement correctly handles an exception?", ["try / except", "if / catch", "do / rescue", "check / error"], 0, "Easy"),
        ("What does `is` compare?", ["Object identity", "String contents only", "Numeric value only", "Collection length"], 0, "Medium"),
        ("Which operation is typically O(1) on average for a dictionary?", ["Lookup by key", "Sort all keys", "Find the smallest value", "Copy every item"], 0, "Medium"),
        ("What does `enumerate(items)` provide?", ["Indexes paired with values", "Only the last item", "A sorted copy", "Unique values"], 0, "Easy"),
        ("Which keyword defines an asynchronous function?", ["async", "await", "yield", "defer"], 0, "Easy"),
        ("What is the purpose of `__init__` in a class?", ["Initialize a new instance", "Delete an instance", "Declare a module", "Catch exceptions"], 0, "Easy"),
        ("What does `with open(path) as file:` help ensure?", ["The file is closed when the block exits", "The file is encrypted", "The file is read in reverse", "The file is globally opened once"], 0, "Medium"),
        ("Which built-in type is immutable?", ["tuple", "list", "set", "dict"], 0, "Easy"),
        ("What does `*args` collect in a function definition?", ["Extra positional arguments", "Extra keyword arguments", "Return values", "Imported modules"], 0, "Medium"),
        ("Which method adds one item to the end of a list?", ["append", "add", "insert_end", "push_back"], 0, "Easy"),
        ("What does `if __name__ == '__main__':` commonly do?", ["Runs code only when the file is executed directly", "Prevents imports", "Declares a package", "Enables type checking"], 0, "Medium"),
        ("What is a decorator commonly used for?", ["Wrap or extend a function or class", "Convert a list to a tuple", "Create a package index", "Declare a constant"], 0, "Medium"),
        ("Which module is commonly used to create isolated temporary directories?", ["tempfile", "pathlib", "glob", "pickle"], 0, "Medium"),
        ("What does `zip(a, b)` do?", ["Pairs corresponding elements", "Sorts both inputs", "Removes duplicates", "Concatenates strings only"], 0, "Easy"),
        ("Why use a virtual environment?", ["Isolate project dependencies", "Speed up the CPU", "Encrypt source files", "Replace the interpreter"], 0, "Easy"),
        ("What does `finally` do in exception handling?", ["Runs cleanup whether or not an exception occurred", "Suppresses every exception", "Retries the try block", "Runs only if there was no exception"], 0, "Medium"),
    ],
    "Java": [
        ("Which collection allows duplicate elements and preserves their order?", ["HashSet", "ArrayList", "TreeSet", "Map"], 1, "Easy"),
        ("Which keyword prevents a class from being subclassed?", ["static", "final", "const", "volatile"], 1, "Easy"),
        ("What is method overloading?", ["Same method name with different parameter lists", "Replacing a parent method", "Calling a method recursively", "Making a method private"], 0, "Medium"),
        ("Which primitive type represents a true or false value?", ["Boolean", "boolean", "Bit", "Truth"], 1, "Easy"),
        ("What does `static` indicate for a field?", ["It belongs to the class rather than each instance", "It cannot be read", "It is always immutable", "It is available only in constructors"], 0, "Medium"),
        ("Which block handles an exception?", ["catch", "handle", "rescue", "except"], 0, "Easy"),
        ("What is the purpose of a Java interface?", ["Define a contract that implementing types provide", "Allocate memory manually", "Store only constants", "Start a thread automatically"], 0, "Medium"),
        ("Which collection is designed for key-value pairs?", ["Set", "Map", "Queue", "List"], 1, "Easy"),
        ("What does `==` compare for two object references?", ["Whether they refer to the same object", "Their fields recursively", "Their hash codes only", "Their class names"], 0, "Medium"),
        ("Which method should generally be overridden when defining value equality?", ["equals", "compare", "sameAs", "identity"], 0, "Medium"),
        ("What does a constructor do?", ["Initializes an object when it is created", "Destroys an object", "Imports a package", "Starts the JVM"], 0, "Easy"),
        ("Which access modifier allows access only within the declaring class?", ["public", "protected", "private", "package"], 2, "Easy"),
        ("What does `try-with-resources` provide?", ["Automatic closing of AutoCloseable resources", "Automatic exception retry", "Thread-safe access to all fields", "Automatic transaction commits"], 0, "Medium"),
        ("Which keyword is used to implement an interface?", ["extends", "implements", "inherits", "instanceof"], 1, "Easy"),
        ("What is the result of integer division `7 / 2` in Java?", ["3", "3.5", "4", "A compilation error"], 0, "Easy"),
        ("Which type is immutable in standard Java?", ["String", "StringBuilder", "ArrayList", "HashMap"], 0, "Easy"),
        ("What does `@Override` help the compiler verify?", ["A method is intended to override an inherited method", "A class is immutable", "A field is injected", "A method is asynchronous"], 0, "Medium"),
        ("Which construct is typically used to process each item in a collection?", ["Enhanced for loop", "switch expression", "synchronized block", "package declaration"], 0, "Easy"),
        ("What does `volatile` primarily provide for a field?", ["Visibility of updates across threads", "Atomic increment operations", "Immutability", "Automatic locking of every method"], 0, "Hard"),
        ("Which exception category must a method catch or declare?", ["Checked exceptions", "All RuntimeExceptions", "Errors only", "AssertionErrors"], 0, "Medium"),
    ],
    "JavaScript": [
        ("Which declaration creates a block-scoped variable that can be reassigned?", ["var", "let", "const", "static"], 1, "Easy"),
        ("What does `===` check?", ["Value and type without coercion", "Value after coercion", "Object identity only", "Whether a value is truthy"], 0, "Easy"),
        ("What does an `async` function always return?", ["A Promise", "A generator", "A callback", "An event"], 0, "Easy"),
        ("Which array method transforms each element into a new array?", ["map", "filter", "reduce", "find"], 0, "Easy"),
        ("What does `Array.prototype.filter` return?", ["A new array containing values that pass a predicate", "The first matching value", "A boolean", "The original array sorted"], 0, "Easy"),
        ("What is a closure?", ["A function retaining access to its lexical scope", "A function with no parameters", "A closed network connection", "A class constructor"], 0, "Medium"),
        ("What does `Promise.all` do if one input promise rejects?", ["Rejects with that rejection", "Waits forever", "Ignores the rejected promise", "Returns only fulfilled values"], 0, "Medium"),
        ("What does optional chaining (`?.`) do?", ["Stops property access when the left side is nullish", "Catches every exception", "Declares an optional function", "Converts a value to a boolean"], 0, "Medium"),
        ("What is the result of `typeof null` in JavaScript?", ["null", "object", "undefined", "boolean"], 1, "Medium"),
        ("What is event bubbling?", ["Propagation from a target element up through ancestors", "Repeating a handler until true", "Dispatching an event to a worker", "Delaying an event until page load"], 0, "Medium"),
        ("Which syntax creates a shallow copy of an object?", ["{ ...source }", "Object.freeze(source)", "source.prototype", "new Object(source, true)"], 0, "Easy"),
        ("What does `const` prevent?", ["Reassignment of the binding", "Changes to every nested property", "Reading the variable", "Use before declaration"], 0, "Easy"),
        ("Which method converts a JSON string into a JavaScript value?", ["JSON.parse", "JSON.stringify", "JSON.decode", "JSON.toObject"], 0, "Easy"),
        ("What is the purpose of `Array.prototype.reduce`?", ["Accumulate array values into a single result", "Remove all falsy values", "Create a sorted copy", "Return the first item"], 0, "Medium"),
        ("When does a `finally` block on a Promise chain run?", ["After fulfillment or rejection", "Only after fulfillment", "Only after rejection", "Before the promise settles"], 0, "Medium"),
        ("What does `event.preventDefault()` do?", ["Cancels the browser's default action", "Stops propagation to ancestors", "Removes the event listener", "Prevents JavaScript execution"], 0, "Easy"),
        ("What is a microtask in JavaScript?", ["A queued task such as a Promise reaction processed before the next task", "A Web Worker", "A synchronous network request", "A module type"], 0, "Hard"),
        ("What does `Object.freeze` do?", ["Prevents changes to an object's own properties", "Deep-freezes every nested object", "Serializes an object", "Makes an object iterable"], 0, "Medium"),
        ("What does destructuring do?", ["Extracts values from arrays or properties from objects", "Copies an object deeply", "Converts values to strings", "Declares private class fields"], 0, "Easy"),
        ("Which statement about JavaScript modules is correct?", ["`import` and `export` provide a module interface", "`require` is the only supported syntax", "Modules share all local variables globally", "An exported binding must be a class"], 0, "Medium"),
    ],
    "React": [
        ("Which hook stores local component state?", ["useState", "useMemo", "useRef", "useContext"], 0, "Easy"),
        ("Why should a list item have a stable `key`?", ["Help React identify items across renders", "Enable CSS modules", "Make the item mutable", "Prevent event bubbling"], 0, "Easy"),
        ("What should a component do with props?", ["Treat them as read-only inputs", "Modify them directly", "Store them in local storage", "Use them only in effects"], 0, "Easy"),
        ("When does an effect with an empty dependency array generally run?", ["After the component first mounts", "Before every render", "Only when unmounted", "Once per state update"], 0, "Medium"),
        ("What does a controlled input use as its source of truth?", ["React state passed through value and updated by a handler", "The DOM only", "A CSS selector", "A URL fragment"], 0, "Medium"),
        ("What is a React fragment used for?", ["Group elements without an extra DOM node", "Create a portal", "Memoize a callback", "Catch network errors"], 0, "Easy"),
        ("What does lifting state up mean?", ["Move shared state to a common ancestor", "Move state into CSS", "Persist state in a server", "Replace state with props everywhere"], 0, "Medium"),
        ("What does `useMemo` primarily cache?", ["A computed value between renders", "A DOM node", "A network response permanently", "A component's props"], 0, "Medium"),
        ("What does `useCallback` return?", ["A memoized function reference", "A memoized object value", "A DOM element", "A promise"], 0, "Medium"),
        ("Why should state updates avoid mutating existing objects?", ["React relies on new references to detect changes reliably", "Objects cannot contain state", "Mutation prevents event handlers", "It disables JSX"], 0, "Medium"),
        ("What does a custom hook need to follow?", ["Hook rules and a name beginning with `use`", "It must return JSX", "It must be a class", "It must run only on click"], 0, "Medium"),
        ("What is a portal useful for?", ["Render children into a different DOM node", "Share state across servers", "Replace a router", "Create a new React root on every render"], 0, "Medium"),
        ("What does `useRef` provide?", ["A mutable reference that persists across renders without triggering a render", "A state setter", "A context provider", "A derived prop"], 0, "Medium"),
        ("What does React context help avoid?", ["Passing some values through many intermediate components", "All component renders", "Using state", "Handling user input"], 0, "Medium"),
        ("What is reconciliation?", ["React's process for updating the DOM based on render output", "A CSS layout algorithm", "A test runner", "An HTTP retry"], 0, "Hard"),
        ("What does an error boundary catch?", ["Rendering errors in descendant components", "Every asynchronous error", "Errors in event handlers", "Server errors before a request"], 0, "Hard"),
        ("When should an effect's cleanup function run?", ["Before the effect reruns and when the component unmounts", "Only before the first render", "Only after a failed render", "After every click"], 0, "Medium"),
        ("What can cause an infinite effect loop?", ["An effect updates a dependency on every run", "A component has a key", "A handler is passed as a prop", "A fragment has two children"], 0, "Hard"),
        ("What does `React.memo` commonly optimize?", ["Unnecessary rerenders when props are unchanged", "Network requests", "DOM event propagation", "CSS parsing"], 0, "Medium"),
        ("What is the purpose of a Suspense boundary?", ["Show a fallback while supported content is not ready", "Catch every JavaScript exception", "Memoize state", "Prevent unmounting"], 0, "Medium"),
    ],
    "SQL": [
        ("Which clause filters rows before grouping?", ["WHERE", "HAVING", "ORDER BY", "LIMIT"], 0, "Easy"),
        ("Which clause filters groups after aggregation?", ["WHERE", "HAVING", "FROM", "OFFSET"], 1, "Easy"),
        ("What does an INNER JOIN return?", ["Rows with matching join keys in both inputs", "Every row from the left input", "Every possible row pair", "Only unmatched rows"], 0, "Easy"),
        ("What is a primary key?", ["A column or column set that uniquely identifies each row", "An index that permits duplicate rows", "A reference to any external table", "A required sort order"], 0, "Easy"),
        ("What does a foreign key enforce?", ["A relationship to valid referenced rows", "Unique values in every column", "Automatic sorting", "Encryption at rest"], 0, "Medium"),
        ("Which aggregate counts rows?", ["COUNT(*)", "SUM(*)", "TOTAL(*)", "ROWS(*)"], 0, "Easy"),
        ("What does `GROUP BY` do?", ["Groups rows for aggregate calculations", "Sorts rows alphabetically", "Removes every duplicate row", "Combines tables"], 0, "Easy"),
        ("What does `COALESCE(a, b)` return?", ["The first non-NULL argument", "The largest argument", "The sum of both arguments", "NULL if either argument is NULL"], 0, "Medium"),
        ("Which condition correctly tests for a NULL value?", ["column IS NULL", "column = NULL", "column == NULL", "column EQUALS NULL"], 0, "Easy"),
        ("What is a database transaction intended to provide?", ["A unit of work with commit or rollback behavior", "A permanent table lock", "A query execution plan", "A backup file"], 0, "Medium"),
        ("What does `ORDER BY created_at DESC` do?", ["Sorts later timestamps first", "Groups identical timestamps", "Removes NULL timestamps", "Sorts oldest timestamps first"], 0, "Easy"),
        ("Which statement adds a new row?", ["INSERT", "ALTER", "CREATE", "GRANT"], 0, "Easy"),
        ("What does `UPDATE` modify?", ["Values in existing rows", "The database engine", "A query plan only", "Table relationships only"], 0, "Easy"),
        ("Which constraint prevents duplicate values in a column or column set?", ["UNIQUE", "CHECK", "DEFAULT", "NOT NULL"], 0, "Easy"),
        ("What is an index primarily used for?", ["Speeding up selected data lookups", "Guaranteeing every query is faster", "Replacing primary keys", "Compressing query results"], 0, "Medium"),
        ("What does `LEFT JOIN` preserve?", ["All rows from the left input", "All rows from the right input only", "Only unmatched rows", "Only matching rows"], 0, "Easy"),
        ("Why use parameterized queries?", ["Safely bind values instead of building SQL from untrusted input", "Guarantee an index is used", "Prevent all database errors", "Automatically normalize a schema"], 0, "Medium"),
        ("What does `COUNT(column)` generally exclude?", ["Rows where that column is NULL", "Rows where that column is zero", "Duplicate values", "Rows with empty strings"], 0, "Medium"),
        ("Which command removes rows matching a condition?", ["DELETE", "DROP", "TRUNCATE DATABASE", "REMOVE"], 0, "Easy"),
        ("What does normalization generally aim to reduce?", ["Redundant data and update anomalies", "The number of valid queries", "The need for keys", "The use of transactions"], 0, "Medium"),
    ],
}

TECHNOLOGY_ALIASES = {
    "python": "Python",
    "fastapi": "Python",
    "java": "Java",
    "javascript": "JavaScript",
    "typescript": "JavaScript",
    "react": "React",
    "node.js": "JavaScript",
    "sql": "SQL",
    "postgresql": "SQL",
    "mysql": "SQL",
    "sqlite": "SQL",
}


def detect_assessment_topic(required_skills: list[str], candidate_text: str) -> str | None:
    lowered = candidate_text.lower()
    detected: dict[str, tuple[int, int]] = {}
    for skill, topic in TECHNOLOGY_ALIASES.items():
        matches = re.findall(rf"(?<!\w){re.escape(skill)}(?!\w)", lowered)
        occurrences = len(matches)
        if not occurrences:
            continue
        relevant = int(any(skill == requirement.lower().strip() for requirement in required_skills))
        current = detected.get(topic, (0, 0))
        detected[topic] = max(current, (relevant, occurrences))
    if not detected:
        return None
    return max(detected, key=lambda topic: (detected[topic][0], detected[topic][1]))


def get_questions(topic: str) -> list[tuple[str, list[str], int, str]]:
    return QUESTION_BANKS[topic]

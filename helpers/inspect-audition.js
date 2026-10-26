// Explicit read-only inspection. No activate, click, keystroke, set or transport call.
// Bounds avoid traversing an entire document or an unbounded Accessibility tree.
function run(argv) {
    const result = {read_only: true, transport_state: 'unknown', nodes: [], truncated: false};
    try {
        if (argv.length !== 1 || !/^com\.adobe\.[A-Za-z0-9.]*audition[A-Za-z0-9.]*$/i.test(argv[0]))
            throw new Error('Unexpected Audition bundle identifier.');
        const se = Application('System Events');
        const processes = se.applicationProcesses.whose({bundleIdentifier: argv[0]})();
        if (!processes.length) {
            result.status = 'not_running';
            return JSON.stringify(result);
        }
        function read(node, field) {
            try {
                const value = node[field]();
                return (typeof value === 'string' ? value.slice(0, 160) : null);
            } catch (_) { return null; }
        }
        function visit(node, depth, parent) {
            if (result.nodes.length >= 200) {result.truncated = true; return;}
            const index = result.nodes.length;
            result.nodes.push({parent: parent, role: read(node, 'role'),
                name: read(node, 'name'), description: read(node, 'description')});
            // Never read text/value attributes: they may contain programme content.
            const children = node.uiElements();
            if (depth >= 5) {if (children.length) result.truncated = true; return;}
            if (children.length > 40) result.truncated = true;
            for (let i = 0; i < Math.min(children.length, 40); i++) visit(children[i], depth + 1, index);
        }
        visit(processes[0], 0, null);
        result.status = 'observed';
    } catch (error) {
        result.status = 'unavailable';
        result.error = String(error).slice(0, 600);
    }
    return JSON.stringify(result);
}

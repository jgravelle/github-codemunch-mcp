import * as vscode from "vscode";
import { spawn } from "child_process";
import * as path from "path";

const CODE_EXTS = new Set<string>([
    ".py", ".pyi",
    ".js", ".jsx", ".mjs", ".cjs",
    ".ts", ".tsx", ".mts", ".cts",
    ".go", ".rs", ".java", ".php", ".rb",
    ".cs", ".cshtml", ".razor",
    ".cpp", ".c", ".h", ".hpp", ".cc", ".cxx",
    ".swift", ".kt", ".kts", ".scala", ".dart",
    ".lua", ".luau", ".ex", ".exs", ".erl", ".hrl",
    ".vue", ".svelte", ".sql",
    ".gd", ".al", ".gleam", ".nix",
    ".hcl", ".tf", ".proto", ".graphql", ".gql",
    ".jl", ".r", ".R", ".hs",
    ".f90", ".f95", ".f03", ".f08",
    ".groovy", ".pl", ".pm",
    ".bash", ".sh", ".zsh",
]);

const pendingTimers = new Map<string, NodeJS.Timeout>();
let outputChannel: vscode.OutputChannel | undefined;

function getChannel(): vscode.OutputChannel {
    if (!outputChannel) {
        outputChannel = vscode.window.createOutputChannel("jCodeMunch");
    }
    return outputChannel;
}

function matchesAny(filePath: string, patterns: string[]): boolean {
    const rel = vscode.workspace.asRelativePath(filePath, false);
    for (const pat of patterns) {
        const re = globToRegex(pat);
        if (re.test(rel) || re.test(filePath)) return true;
    }
    return false;
}

function globToRegex(glob: string): RegExp {
    const escaped = glob
        .replace(/[.+^${}()|[\]\\]/g, "\\$&")
        .replace(/\*\*/g, "::DOUBLESTAR::")
        .replace(/\*/g, "[^/\\\\]*")
        .replace(/::DOUBLESTAR::/g, ".*")
        .replace(/\?/g, ".");
    return new RegExp("^" + escaped + "$");
}

function reindex(filePath: string) {
    const cfg = vscode.workspace.getConfiguration("jcodemunch.indexOnSave");
    const cmd = cfg.get<string>("command", "jcodemunch-mcp");
    const ch = getChannel();

    const child = spawn(cmd, ["index-file", filePath], {
        stdio: ["ignore", "pipe", "pipe"],
        windowsHide: true,
    });

    let stderr = "";
    child.stderr?.on("data", (d) => { stderr += d.toString(); });

    child.on("error", (err) => {
        ch.appendLine(`[error] ${cmd} failed: ${err.message}`);
    });
    child.on("exit", (code) => {
        if (code === 0) {
            ch.appendLine(`[ok] reindexed ${filePath}`);
        } else {
            ch.appendLine(`[exit ${code}] ${filePath}${stderr ? ": " + stderr.trim() : ""}`);
        }
    });
}

function scheduleReindex(filePath: string) {
    const cfg = vscode.workspace.getConfiguration("jcodemunch.indexOnSave");
    if (!cfg.get<boolean>("enabled", true)) return;

    const ext = path.extname(filePath).toLowerCase();
    if (!CODE_EXTS.has(ext)) return;

    const exclude = cfg.get<string[]>("exclude", []);
    if (matchesAny(filePath, exclude)) return;

    const debounceMs = cfg.get<number>("debounceMs", 500);
    const existing = pendingTimers.get(filePath);
    if (existing) clearTimeout(existing);

    const timer = setTimeout(() => {
        pendingTimers.delete(filePath);
        reindex(filePath);
    }, debounceMs);
    pendingTimers.set(filePath, timer);
}

export function activate(context: vscode.ExtensionContext) {
    const ch = getChannel();
    ch.appendLine("jCodeMunch auto-reindex active.");

    context.subscriptions.push(
        vscode.workspace.onDidSaveTextDocument((doc) => {
            if (doc.uri.scheme !== "file") return;
            scheduleReindex(doc.uri.fsPath);
        }),
    );
}

export function deactivate() {
    for (const t of pendingTimers.values()) clearTimeout(t);
    pendingTimers.clear();
}

/**
 * SDK ↔ Shell drift detection test.
 *
 * Verifies that desktop/shell/src/acp-types.ts and desktop/shell/src/acp-parse.ts
 * are byte-for-byte identical to what `sync_to_shell.mjs` would produce from the
 * current SDK sources — except for the AUTO-SYNCED banner line and the import
 * path rewrite in parse.ts.
 *
 * IMPORTANT: This test NEVER writes any files.  It replicates the sync
 * transformation in-memory and diffs the result against the committed shell
 * copies.  If this test is red, run `npm run sync-to-shell` from desktop/sdk/
 * and commit the updated shell copies.
 *
 * The previous implementation called execSync(sync_to_shell.mjs) in a before()
 * hook, which silently overwrote any hand-edits to the shell copies before
 * comparing — guaranteeing a false-green even when the files diverged.  That
 * approach has been removed.
 */

import { readFileSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";
import { describe, it } from "node:test";
import assert from "node:assert/strict";

const __dirname = dirname(fileURLToPath(import.meta.url));
const SDK_SRC = join(__dirname, "..", "src");
const SHELL_SRC = join(__dirname, "..", "..", "shell", "src");

const BANNER = "// AUTO-SYNCED from sdk — do not edit; regenerate with: npm run sync-to-shell\n";

// ── In-memory replication of sync_to_shell.mjs transformation ───────────────

/** Inject banner immediately after the first closing block-comment line ("* /"). */
function injectBanner(content: string): string {
    const blockEnd = content.indexOf("*/");
    if (blockEnd !== -1) {
        const afterNewline = blockEnd + 3; // skip "*/" + its trailing "\n"
        return content.slice(0, afterNewline) + BANNER + content.slice(afterNewline);
    }
    return BANNER + content;
}

/** Rewrite SDK import paths to shell import paths (same logic as sync script). */
function rewriteImports(content: string): string {
    return content
        .replace(/from ["']\.\/types\.js["']/g, 'from "./acp-types.js"')
        .replace(/import type \{([^}]+)\} from ["']\.\/types\.js["']/g,
            'import type {$1} from "./acp-types.js"');
}

/**
 * Compute what sync_to_shell would write for types.ts → acp-types.ts.
 * Returns the expected content of shell/src/acp-types.ts.
 */
function computeExpectedTypes(): string {
    const sdkSource = readFileSync(join(SDK_SRC, "types.ts"), "utf-8");
    return injectBanner(sdkSource);
}

/**
 * Compute what sync_to_shell would write for parse.ts → acp-parse.ts.
 * Returns the expected content of shell/src/acp-parse.ts.
 */
function computeExpectedParse(): string {
    const sdkSource = readFileSync(join(SDK_SRC, "parse.ts"), "utf-8");
    return injectBanner(rewriteImports(sdkSource));
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe("SDK → Shell sync drift", () => {
    it("shell/src/acp-types.ts matches what sync_to_shell would produce (no files written)", () => {
        const expected = computeExpectedTypes();
        const actual = readFileSync(join(SHELL_SRC, "acp-types.ts"), "utf-8");

        assert.equal(
            actual,
            expected,
            [
                "acp-types.ts is out of sync with sdk/src/types.ts.",
                "Run `npm run sync-to-shell` from desktop/sdk/ and commit the result.",
            ].join("\n"),
        );
    });

    it("shell/src/acp-parse.ts matches what sync_to_shell would produce (no files written)", () => {
        const expected = computeExpectedParse();
        const actual = readFileSync(join(SHELL_SRC, "acp-parse.ts"), "utf-8");

        assert.equal(
            actual,
            expected,
            [
                "acp-parse.ts is out of sync with sdk/src/parse.ts.",
                "Run `npm run sync-to-shell` from desktop/sdk/ and commit the result.",
            ].join("\n"),
        );
    });

    it("shell copies contain the AUTO-SYNCED banner", () => {
        for (const shellFile of ["acp-types.ts", "acp-parse.ts"]) {
            const content = readFileSync(join(SHELL_SRC, shellFile), "utf-8");
            assert.ok(
                content.includes(BANNER.trimEnd()),
                `${shellFile} must contain the AUTO-SYNCED banner line`,
            );
        }
    });
});

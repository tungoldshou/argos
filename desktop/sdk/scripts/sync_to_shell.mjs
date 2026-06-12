#!/usr/bin/env node
/**
 * SDK → Shell sync script.
 *
 * Copies desktop/sdk/src/types.ts and desktop/sdk/src/parse.ts into
 * desktop/shell/src/ with an AUTO-SYNCED banner injected at the top.
 *
 * Usage:
 *   node scripts/sync_to_shell.mjs          # from desktop/sdk/
 *   npm run sync-to-shell                   # via package.json script
 *
 * The banner line looks like:
 *   // AUTO-SYNCED from sdk — do not edit; regenerate with: npm run sync-to-shell
 *
 * shell/src/acp-types.ts  ← sdk/src/types.ts
 * shell/src/acp-parse.ts  ← sdk/src/parse.ts  (import path rewritten)
 *
 * Import rewrite: sdk uses `./types.js`; shell uses `./acp-types.js`.
 */

import { readFileSync, writeFileSync, mkdirSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

// Paths relative to desktop/sdk/scripts/
const SDK_SRC = join(__dirname, "..", "src");
const SHELL_SRC = join(__dirname, "..", "..", "shell", "src");

const BANNER =
    "// AUTO-SYNCED from sdk — do not edit; regenerate with: npm run sync-to-shell\n";

/** Read a file, inject banner, optionally rewrite imports, write to dest. */
function sync(srcFile, dstFile, rewrite) {
    const content = readFileSync(srcFile, "utf-8");
    let out = content;
    if (rewrite) {
        out = rewrite(out);
    }
    // Inject banner on the line immediately after the closing */ of the first
    // block comment.  The SDK source pattern is "*/\n\n<content>"; we insert
    // the banner between the first and second \n so the result is
    // "*/\n// AUTO-SYNCED...\n\n<content>".  Stripping the banner line then
    // restores the original byte-for-byte.
    const blockEnd = out.indexOf("*/");
    let injected;
    if (blockEnd !== -1) {
        // blockEnd+2 is the char right after "*/", which is "\n".
        // We insert the banner AFTER that first "\n" so we don't add an
        // extra blank line.
        const afterNewline = blockEnd + 3; // skip "*/" and its trailing "\n"
        injected = out.slice(0, afterNewline) + BANNER + out.slice(afterNewline);
    } else {
        injected = BANNER + out;
    }
    mkdirSync(SHELL_SRC, { recursive: true });
    writeFileSync(dstFile, injected, "utf-8");
    console.log(`synced: ${srcFile} → ${dstFile}`);
}

// Sync types.ts → acp-types.ts (no import rewrite needed)
sync(
    join(SDK_SRC, "types.ts"),
    join(SHELL_SRC, "acp-types.ts"),
    null,
);

// Sync parse.ts → acp-parse.ts (rewrite import path)
sync(
    join(SDK_SRC, "parse.ts"),
    join(SHELL_SRC, "acp-parse.ts"),
    (content) =>
        content
            .replace(/from ["']\.\/types\.js["']/g, 'from "./acp-types.js"')
            .replace(/import type \{([^}]+)\} from ["']\.\/types\.js["']/g,
                'import type {$1} from "./acp-types.js"'),
);

console.log("sync-to-shell complete.");

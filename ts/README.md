# gitstore (TypeScript)

A versioned filesystem backed by a bare git repository.

This is the TypeScript port of [gitstore](https://github.com/mhalle/vost), using [isomorphic-git](https://isomorphic-git.org/) as the git backend.

## Usage

```typescript
import { GitStore } from 'gitstore';
import fs from 'node:fs';

const store = new GitStore('my-repo.git', { create: true, fs });

const branch = store.branches.get('main');
await branch.write('hello.txt', 'world');

const content = await branch.readText('hello.txt');
console.log(content); // "world"
```

## License

Apache-2.0 — see [LICENSE](../LICENSE) for details.

package vost.interop

fun main(args: Array<String>) {
    if (args.isEmpty()) {
        System.err.println("Usage: vost-interop <write|read> ...")
        System.exit(1)
    }
    when (args[0]) {
        "write" -> {
            if (args.size < 3) {
                System.err.println("Usage: vost-interop write <fixtures.json> <output_dir>")
                System.exit(1)
            }
            KtWrite.main(args[1], args[2])
        }
        "read" -> {
            if (args.size < 3) {
                System.err.println("Usage: vost-interop read <fixtures.json> <repo_dir> [prefix]")
                System.exit(1)
            }
            val prefix = if (args.size > 3) args[3] else "kt"
            KtRead.main(args[1], args[2], prefix)
        }
        else -> {
            System.err.println("Unknown command: ${args[0]}")
            System.exit(1)
        }
    }
}

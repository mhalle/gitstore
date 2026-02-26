#include "internal.h"
#include "vost/error.h"

#include <filesystem>
#include <string>
#include <functional>
#include <chrono>
#include <thread>

#ifdef VOST_POSIX_LOCK
#  include <fcntl.h>
#  include <sys/file.h>
#  include <unistd.h>
#  include <errno.h>
#  include <cstring>
#endif

#ifdef _WIN32
#  include <windows.h>
#endif

namespace vost {
namespace lock {

#ifdef VOST_POSIX_LOCK

/// RAII POSIX flock guard.
struct FlockGuard {
    int fd;
    explicit FlockGuard(int f) : fd(f) {}
    ~FlockGuard() {
        if (fd >= 0) {
            ::flock(fd, LOCK_UN);
            ::close(fd);
        }
    }
    FlockGuard(const FlockGuard&) = delete;
    FlockGuard& operator=(const FlockGuard&) = delete;
};

/// Acquire an advisory file lock on `<gitdir>/vost.lock`, execute `fn`,
/// then release.  Retries for up to 30 seconds.
void with_repo_lock(const std::filesystem::path& gitdir,
                    std::function<void()> fn) {
    auto lock_path = gitdir / "vost.lock";
    auto lock_str  = lock_path.string();

    // Open/create the lock file
    int fd = ::open(lock_str.c_str(), O_RDWR | O_CREAT | O_CLOEXEC, 0600);
    if (fd < 0) {
        throw IoError("cannot open lock file: " + lock_str +
                      ": " + std::strerror(errno));
    }

    // Retry with backoff for up to 30 seconds
    using namespace std::chrono;
    auto deadline = steady_clock::now() + seconds(30);
    while (true) {
        int rc = ::flock(fd, LOCK_EX | LOCK_NB);
        if (rc == 0) break; // acquired

        if (errno != EWOULDBLOCK) {
            ::close(fd);
            throw IoError(std::string("flock failed: ") + std::strerror(errno));
        }

        if (steady_clock::now() >= deadline) {
            ::close(fd);
            throw VostError("timeout waiting for repo lock: " + lock_str);
        }

        std::this_thread::sleep_for(milliseconds(50));
    }

    FlockGuard guard(fd);
    fn();
    // guard destructor releases lock + closes fd
}

#elif defined(_WIN32)

void with_repo_lock(const std::filesystem::path& gitdir,
                    std::function<void()> fn) {
    auto lock_path = gitdir / "vost.lock";
    auto lock_str  = lock_path.string();

    using namespace std::chrono;
    auto deadline = steady_clock::now() + seconds(30);

    HANDLE h = INVALID_HANDLE_VALUE;
    while (true) {
        h = CreateFileA(lock_str.c_str(),
                        GENERIC_WRITE, 0 /* exclusive */, nullptr,
                        CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (h != INVALID_HANDLE_VALUE) break;

        if (steady_clock::now() >= deadline) {
            throw VostError("timeout waiting for repo lock: " + lock_str);
        }

        std::this_thread::sleep_for(milliseconds(50));
    }

    OVERLAPPED ov = {};
    LockFileEx(h, LOCKFILE_EXCLUSIVE_LOCK, 0, MAXDWORD, MAXDWORD, &ov);

    try {
        fn();
    } catch (...) {
        UnlockFileEx(h, 0, MAXDWORD, MAXDWORD, &ov);
        CloseHandle(h);
        throw;
    }

    UnlockFileEx(h, 0, MAXDWORD, MAXDWORD, &ov);
    CloseHandle(h);
}

#else
// Fallback: no-op (single-process, single-thread only)
void with_repo_lock(const std::filesystem::path& /*gitdir*/,
                    std::function<void()> fn) {
    fn();
}
#endif

} // namespace lock
} // namespace vost

package vost

import org.junit.jupiter.api.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class GlobTest {

    @Test
    fun `globMatch basic patterns`() {
        assertTrue(globMatch("*.txt", "hello.txt"))
        assertTrue(globMatch("*.txt", "world.txt"))
        assertFalse(globMatch("*.txt", "hello.py"))
    }

    @Test
    fun `globMatch question mark`() {
        assertTrue(globMatch("?.txt", "a.txt"))
        assertFalse(globMatch("?.txt", "ab.txt"))
    }

    @Test
    fun `globMatch dotfile protection`() {
        // * does not match leading dot
        assertFalse(globMatch("*", ".hidden"))
        assertFalse(globMatch("*.txt", ".hidden.txt"))

        // Explicit dot pattern matches
        assertTrue(globMatch(".*", ".hidden"))
        assertTrue(globMatch(".?idden", ".hidden"))
    }

    @Test
    fun `globMatch exact match`() {
        assertTrue(globMatch("hello", "hello"))
        assertFalse(globMatch("hello", "world"))
    }

    @Test
    fun `globMatch complex patterns`() {
        assertTrue(globMatch("test_*", "test_foo"))
        assertTrue(globMatch("*_test", "foo_test"))
        assertTrue(globMatch("a*b", "axyzb"))
        assertFalse(globMatch("a*b", "axyzc"))
    }
}

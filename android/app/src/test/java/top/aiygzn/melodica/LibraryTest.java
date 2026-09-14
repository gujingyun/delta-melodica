package top.aiygzn.melodica;

import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class LibraryTest {
    @Rule public TemporaryFolder temporary = new TemporaryFolder();

    @Test public void includesUnlockSongsAsBuiltins() throws Exception {
        Library library = new Library(temporary.newFolder());

        assertEquals(Library.BUILTIN_COUNT, library.entries().size());
        for (String id : new String[]{"unlock-nightingale", "unlock-watch", "unlock-wind", "unlock-dawn"}) {
            assertTrue(Library.isBuiltin(id));
            Score score = library.read(id);
            assertTrue(score.title.startsWith("乐曲解锁-"));
            assertFalse(score.notes.isEmpty());
        }
        assertFalse(Library.isBuiltin("imported.json"));
    }
}

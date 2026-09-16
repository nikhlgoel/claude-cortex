//Decompiles every function in the program to a single C file.
//
//Ghidra's headless analyzer produces a project database, not source. This script
//is what turns an analysed binary into something readable, which is the whole
//point of the integration: the value is not "Ghidra ran", it is "here is the
//recovered logic, as text a person or a model can reason over".
//
//Usage (headless):
//  analyzeHeadless <proj_dir> <proj_name> -import <binary> \
//    -scriptPath <dir> -postScript DecompileToC.java <output.c>
//
//@category Cortex
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.List;

import ghidra.app.decompiler.DecompInterface;
import ghidra.framework.Application;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;

public class DecompileToC extends GhidraScript {

	// Per-function ceiling. A pathological function can occupy the decompiler
	// far longer than the rest of the binary combined, and a headless run that
	// never returns is indistinguishable from a crash.
	private static final int TIMEOUT_SECONDS = 60;

	@Override
	public void run() throws Exception {
		String[] args = getScriptArgs();
		String outputPath = args.length > 0 ? args[0] : "/work/out/decompiled.c";

		DecompInterface decompiler = new DecompInterface();
		decompiler.setOptions(new DecompileOptions());

		if (!decompiler.openProgram(currentProgram)) {
			println("DecompileToC: could not open program: "
				+ decompiler.getLastMessage());
			return;
		}

		List<String> failed = new ArrayList<>();
		int succeeded = 0;

		try (PrintWriter out = new PrintWriter(outputPath, "UTF-8")) {
			out.println("// Decompiled by Ghidra " + Application.getApplicationVersion());
			out.println("// Source binary: " + currentProgram.getName());
			out.println("// Language: " + currentProgram.getLanguageID());
			out.println("//");
			out.println("// This is RECOVERED logic, not the original source. Names of");
			out.println("// locals are invented, types are inferred, and anything the");
			out.println("// compiler optimised away is gone for good.");
			out.println();

			FunctionIterator functions = currentProgram.getFunctionManager()
					.getFunctions(true);

			while (functions.hasNext() && !monitor.isCancelled()) {
				Function function = functions.next();

				// Thunks and external stubs decompile to nothing useful.
				if (function.isThunk() || function.isExternal()) {
					continue;
				}

				DecompileResults results =
					decompiler.decompileFunction(function, TIMEOUT_SECONDS, monitor);

				if (results != null && results.decompileCompleted()) {
					out.println("// ---- " + function.getName()
						+ "  @ " + function.getEntryPoint() + " ----");
					out.println(results.getDecompiledFunction().getC());
					out.println();
					succeeded++;
				}
				else {
					String why = results == null
							? "no result"
							: results.getErrorMessage();
					failed.add(function.getName() + " (" + why + ")");
				}
			}
		}
		finally {
			decompiler.dispose();
		}

		println("DecompileToC: " + succeeded + " function(s) written to " + outputPath);
		if (!failed.isEmpty()) {
			println("DecompileToC: " + failed.size() + " function(s) failed:");
			for (String name : failed) {
				println("    " + name);
			}
		}
	}
}

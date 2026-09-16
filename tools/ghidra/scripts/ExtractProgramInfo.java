//Extracts structured facts about a program as JSON.
//
//Decompiled C on its own is a wall of text. The question a person actually asks
//first is "what is this thing able to do", and that is answered by what it
//imports, not by reading every function: a binary that never imports a socket
//call cannot open one.
//
//This emits the raw facts. Judgement about what they mean lives in report.py,
//so the two can be changed independently and the facts stay checkable.
//
//Usage (headless):
//  -postScript ExtractProgramInfo.java <output.json>
//
//@category Cortex
import java.io.PrintWriter;
import java.util.ArrayList;
import java.util.List;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;
import ghidra.program.model.symbol.SymbolType;
import ghidra.program.model.data.StringDataInstance;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;

public class ExtractProgramInfo extends GhidraScript {

	// Strings shorter than this are mostly compiler noise and fragments.
	private static final int MIN_STRING_LENGTH = 5;
	private static final int MAX_STRINGS = 400;

	@Override
	public void run() throws Exception {
		String[] args = getScriptArgs();
		String outputPath = args.length > 0 ? args[0] : "/work/out/program.json";

		try (PrintWriter out = new PrintWriter(outputPath, "UTF-8")) {
			out.println("{");

			out.println("  \"name\": " + quote(currentProgram.getName()) + ",");
			out.println("  \"format\": " + quote(currentProgram.getExecutableFormat()) + ",");
			out.println("  \"language\": " + quote(currentProgram.getLanguageID().toString()) + ",");
			out.println("  \"compiler\": " + quote(currentProgram.getCompilerSpec()
					.getCompilerSpecID().toString()) + ",");
			out.println("  \"imageBase\": " + quote(currentProgram.getImageBase().toString()) + ",");
			out.println("  \"executableMD5\": " + quote(String.valueOf(
					currentProgram.getExecutableMD5())) + ",");

			writeImports(out);
			writeExports(out);
			writeFunctions(out);
			writeStrings(out);

			out.println("  \"generatedBy\": \"Ghidra "
				+ ghidra.framework.Application.getApplicationVersion() + "\"");
			out.println("}");
		}

		println("ExtractProgramInfo: written to " + outputPath);
	}

	/** External symbols the binary calls - what it is capable of. */
	private void writeImports(PrintWriter out) {
		List<String> entries = new ArrayList<>();
		SymbolIterator symbols = currentProgram.getSymbolTable().getExternalSymbols();
		while (symbols.hasNext() && !monitor.isCancelled()) {
			Symbol symbol = symbols.next();
			String library = symbol.getParentNamespace() != null
					? symbol.getParentNamespace().getName()
					: "";
			entries.add("    {\"name\": " + quote(symbol.getName())
				+ ", \"library\": " + quote(library) + "}");
		}
		writeArray(out, "imports", entries);
	}

	private void writeExports(PrintWriter out) {
		List<String> entries = new ArrayList<>();
		SymbolIterator symbols =
			currentProgram.getSymbolTable().getAllSymbols(true);
		while (symbols.hasNext() && !monitor.isCancelled()) {
			Symbol symbol = symbols.next();
			if (symbol.isExternalEntryPoint() && symbol.getSymbolType() == SymbolType.FUNCTION) {
				entries.add("    {\"name\": " + quote(symbol.getName())
					+ ", \"address\": " + quote(symbol.getAddress().toString()) + "}");
			}
		}
		writeArray(out, "exports", entries);
	}

	/**
	 * Functions with their size and incoming call count. Call count is a decent
	 * proxy for importance: a function called from twenty places is load-bearing,
	 * one called from nowhere is often dead or an entry point.
	 */
	private void writeFunctions(PrintWriter out) {
		List<String> entries = new ArrayList<>();
		FunctionIterator functions =
			currentProgram.getFunctionManager().getFunctions(true);
		while (functions.hasNext() && !monitor.isCancelled()) {
			Function function = functions.next();
			Address entry = function.getEntryPoint();

			int callers = 0;
			for (Reference reference :
					currentProgram.getReferenceManager().getReferencesTo(entry)) {
				if (reference.getReferenceType().isCall()) {
					callers++;
				}
			}

			entries.add("    {\"name\": " + quote(function.getName())
				+ ", \"address\": " + quote(entry.toString())
				+ ", \"size\": " + function.getBody().getNumAddresses()
				+ ", \"callers\": " + callers
				+ ", \"thunk\": " + function.isThunk()
				+ ", \"external\": " + function.isExternal() + "}");
		}
		writeArray(out, "functions", entries);
	}

	/** Defined strings - often the fastest route to what a binary is for. */
	private void writeStrings(PrintWriter out) {
		List<String> entries = new ArrayList<>();
		// DefinedDataIterator.definedStrings(Program) does not exist in this
		// Ghidra version, so walk defined data and ask each item whether it is
		// a string. StringDataInstance returns NULL_INSTANCE for non-strings.
		int count = 0;
		DataIterator dataItems = currentProgram.getListing().getDefinedData(true);
		while (dataItems.hasNext()) {
			if (monitor.isCancelled() || count >= MAX_STRINGS) {
				break;
			}
			Data data = dataItems.next();
			StringDataInstance instance = StringDataInstance.getStringDataInstance(data);
			if (instance == StringDataInstance.NULL_INSTANCE) {
				continue;
			}
			String value = instance.getStringValue();
			if (value == null || value.length() < MIN_STRING_LENGTH) {
				continue;
			}
			entries.add("    {\"address\": " + quote(data.getAddress().toString())
				+ ", \"value\": " + quote(value) + "}");
			count++;
		}
		writeArray(out, "strings", entries);
	}

	private void writeArray(PrintWriter out, String key, List<String> entries) {
		out.println("  \"" + key + "\": [");
		for (int i = 0; i < entries.size(); i++) {
			out.println(entries.get(i) + (i < entries.size() - 1 ? "," : ""));
		}
		out.println("  ],");
	}

	/** Minimal JSON string escaping - no dependency on a JSON library. */
	private String quote(String text) {
		if (text == null) {
			return "null";
		}
		StringBuilder builder = new StringBuilder("\"");
		for (int i = 0; i < text.length(); i++) {
			char c = text.charAt(i);
			switch (c) {
				case '"' -> builder.append("\\\"");
				case '\\' -> builder.append("\\\\");
				case '\n' -> builder.append("\\n");
				case '\r' -> builder.append("\\r");
				case '\t' -> builder.append("\\t");
				default -> {
					if (c < 0x20 || c > 0x7e) {
						builder.append(String.format("\\u%04x", (int) c));
					}
					else {
						builder.append(c);
					}
				}
			}
		}
		return builder.append('"').toString();
	}
}



Problem with globs:

* prevalidate() calls validation of inputs and outputs. This is the only chance for skipped recipes to get aliases propagated down. I.e. if a sub-recipe has an output that is an alias of a sub-step, and the sub-recipe is skipped, this is the only chance to evaluate the glob (presumably, to existing outputs on disk).

* validate_inputs() called before running a step. Currently this does not evaluate globs.

* validate_outputs() called after running. Here we must re-expand the globs, since running the step may have changed the content.

The current scheme where the glob is expanded and substituted as ``params[name] = [files]`` creates a problem. Expansion needs to happen at prevalidation. Then it needs to happen again at the output stage. So we can't replace the glob with a filelist. Somehow we must retain knowledge that this is a glob, otherwise we won't know to re-evaluate it.

I tried creating a Glob class, but pydantic won't allow that, it expects a list of strings. So we need to retain this information externally (in Cargo, perhaps?)

So: keep a copy of the original params dict, and re-evaluate all globs when asked to.

Consider adding an explicit "glob:" prefix to glob values, so that we know not to re-evaluate explicitly specified files?




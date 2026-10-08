# TODO

Cross-cutting tasks for BC121, the boundary coupled subwoofer with one 21" driver in a front-loaded horn. Tasks that
belong to one specific file go in that file as `% TODO: ...` or `# TODO: ...`.

## Gates

The main steps from idea to a built cabinet. BC121 is a hobby project: a gate is passed when the result is good enough,
there is no formal sign-off.

1. [ ] Fundamental base sketch of the horn (in progress; `Cad\BC121 Fundamental sketch.scdocx`)
2. [ ] Base sketch to 3D design (`Cad\BC121.scdocx`)
3. [ ] Validate the performance (JVsound toolbox with acoustic data from Ansys Mechanical, for example the maximum SPL
   at several positions)
4. [ ] Make it buildable (`Cad\Cabinet Design`, the nesting and the DXF files for cutting)

## Open

- [ ] Finalize the cabinet design in SpaceClaim (`Cad\`); the tasks below wait for it
  - [ ] Nesting export (`Test\dxf\`): check the plate thickness of every part (birch plywood, 18 mm) and report parts
    with another thickness
  - [ ] Nesting export (`Test\dxf\`): list the parts that occur more than once (for example `Sheet 13`, `Sheet 5`), now
    that the cabinet is made twice, so the DXF files show how many of each part to cut

## Other

- [ ] Simulate the maximum SPL at several positions with the JVsound Loudspeaker System Toolbox, using the acoustic data
  from Ansys Mechanical

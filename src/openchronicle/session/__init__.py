"""Session segmentation — cuts the stream of captures into work sessions.

Ported from Einsia-Partner. The SessionManager applies three rules to
decide when a session ends: idle gap (hard cut), unrelated-app switch
(soft cut), or timeout (max 2 h). Each closed session becomes the unit
of S2 reduction in the writer pipeline.
"""

# NAME

bt_pa_auto_switcher.py - Switch Bluetooth headset between A2DP and HSP
automatically with Pulseaudio

# DESCRIPTION

Bluetooth headsets generally support two profiles: High Fidelity
Playback, a.k.a., A2DP, and Telephony Duplex, a.k.a., HSP/HFP or just
HSP. A2DP is for stereo audio output with the microphone disabled; HSP
is for mono output and mono microphone input.

Cell phones seem to be smart enough to know how to do the right thing
automatically, switching back and forth between the A2DP and HSP
profile automatically depending on whether the Microphone is in use,
but Pulseaudio and Bluez, the most common audio and Bluetooth
frameworks for Linux, don't know how to do this.

This script "eavesdrops" on Pulseaudio events and automatically
switches from A2DP to HSP if an application tries to use both output
and input at the same time, then it switches back when everyone is
finished using the microphone.

Furthermore, the script automatically mutes other sound sources while
the microphone is in use and unmutes them afterward.

Finally, it also tries to remember the volume that was set on the
headset for A2DP and HSP/HFP, and restore it when switching between
them, because Pulseaudio doesn't seem to do this automatically and
it's really annoying when it switches to full volume HSP/HFP and your
ears get blasted.

# CONFIGURATION

You need the ["Expect" perl module](http://search.cpan.org/~rgiersig/Expect-1.21/) installed for
this script to work.

Set `$mute_corked` to 0 below if you don't want other applications
muted while you're using the microphone. However, see the caveat
below.

Edit the `$valid_clients` variable below to match the names of
clients for which you want the profile switching to be done. This is
necessary because there are all kinds of "fake" connection events,
e.g., from the sound settings applet. You can find out the correct
client name to use by running `pacmd list-sink-inputs` while the
client is using the microphone and locating its "application.name"
property.  Feel free to email me additions to the list of clients;
I've initially populated it with the apps that I use frequently.

Once the script is configured properly, either start it up manually or
configure something to run it automatically when you log in, e.g., by
adding it as a startup program in gnome-session-properties. When the
script starts up it will wait for up to 30 seconds for Pulseaudio to
start, in case it gets started on login before Pulseaudio is started.

# CAVEATS / TODO

The script in its current form works only with Pulseaudio and
Bluez. It could probably be made more generalized, and I'd happy take
patches to do that.

I'd happily take a patch to replace the usage of the non-standard
Expect module with code that uses only standard Perl modules.

The "module-role-cork" plugin does not seem to play nicely with this
script, so if you want to use this script, you need to disable that
plugin, e.g., by commenting it out in `/etc/pulse/default.pa` and
restarting pulseaudio, even if you set `$mute_corked` to 0. I'd
gladly accept patches to make the script work better with the plugin.

I probably should have written this as a Pulseaudio plugin. However, I
wanted to solve the problem fast, and for me, personally, a Perl
script was the fastest solution.

# THEORY OF OPERATION

The script uses "`pactl subscribe`" to subscribe to Pulseaudio events
and watch for the birth and death of "sink-input" and "source-output"
connections to Pulseaudio. It filters these events using
`$valid_clients` to only pay attention to clients that are known to
actually use the microphone.

When the script notices that there is at least one active sink-input
and source-output that made it through the filter, it finds the active
Bluetooth audio device and switches it to the HSP profile. Before
doing the switch, it saves the current audio volume and then mutes
other clients generating output, unless `$mute_corked` is set to 0.

After doing the switch, it checks to see if it has a saved volume
level from the last time the HSP profile was used, and if so, restores
the volume setting to that level.

When all of the 2-way audio clients have stopped using audio, the
script works in reverse to switch back to A2DP: it saves the volume
for next time, switches back to the A2DP profile, restores the
previous A2DP volume, and unmutes the muted audio output clients.

# SEE ALSO

You may also find useful my
[script](http://blog.kamens.us/2012/10/05/pulseaudio-switch-to-headset-automatically-when-its-plugged-in-docked/)
to switch to a Bluetooth or USB headset automatically when it's
plugged in or paired.

# PEEVES

Like many other things in Pulseaudio, the "division of labor" between
`pactl` and `pacmd` is entirely incomprehensible and seemingly
unnecessary. It's impossible to understand why there isn't one tool
that does everything both of these existing tools do, rather than
functionality being split seemingly arbitrarily between the two tools.

# REPOSITORY

http://github.com/jikamens/bt_pa_auto_switcher

# AUTHOR

Jonathan Kamens <jik@kamens.us>

# COPYRIGHT

Copyright (2) 2013 Jonathan Kamens.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or (at
your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see [http://www.gnu.org/licenses/](http://www.gnu.org/licenses/).
